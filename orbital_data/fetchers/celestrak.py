"""
CelesTrak fetchers for GP (TLE) data and SATCAT ``records.php`` JSON.

Public functions return parsed models and perform HTTP via ``requests``.
Network failures propagate unless the caller handles them; the cache layer
falls back to stale files when refreshes fail.
"""

from __future__ import annotations

import logging
import re
import textwrap
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from models import SatcatRecord, TLE

log = logging.getLogger(__name__)

CELESTRAK_GP_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php"
CELESTRAK_SATCAT_RECORDS_URL = "https://celestrak.org/satcat/records.php"

# TLE groups required by the project (also used as SATCAT ``GROUP`` values).
TLE_SOURCE_GROUPS: tuple[str, ...] = (
    "starlink",
    "stations",
    "fengyun-1c-debris",
    "cosmos-2251-debris",
    "iridium-33-debris",
)


class CelestrakGPUnchangedError(Exception):
    """
    CelesTrak rejected a GP download because the on-orbit element set is
    unchanged since the client's prior successful pull for this ``GROUP``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _gp_unchanged_body(text: str) -> bool:
    return "has not updated since your last successful" in text.lower()


def fetch_tle_group(group: str, session: requests.Session | None = None) -> list[TLE]:
    """
    Download and parse all TLEs for ``group`` from CelesTrak ``gp.php``.

    Returns:
        Fresh :class:`TLE` instances with ``fetched_at`` set to UTC now.

    Raises:
        CelestrakGPUnchangedError: When CelesTrak blocks the consolidated
            ``GROUP`` download *and* the INTDES-based fallback cannot retrieve
            any new elements.
        requests.RequestException: On other HTTP or transport failures.
        ValueError: If the response body is not parseable TLE text.
    """
    sess = session or requests.Session()
    params = {"GROUP": group, "FORMAT": "tle"}
    log.info("Fetching TLE group %r from CelesTrak gp.php", group)
    resp = sess.get(CELESTRAK_GP_TLE_URL, params=params, timeout=120)
    if resp.status_code == 403 and _gp_unchanged_body(resp.text):
        log.warning(
            "CelesTrak GP GROUP=%r returned HTTP 403 unchanged; falling back to INTDES launches",
            group,
        )
        return _fetch_tles_via_intdes_launches(group, sess, orig_hint=resp.text.strip())
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "no gp data found" in text.lower():
        return []
    fetched_at = datetime.now(timezone.utc)
    tles = parse_tle_text(text, source_group=group, fetched_at=fetched_at)
    log.info(
        "Fetched TLE group %r: %d objects at %s",
        group,
        len(tles),
        fetched_at.isoformat(),
    )
    return tles


def _launch_keys_from_satcat_group(group: str, session: requests.Session) -> list[str]:
    resp = session.get(
        CELESTRAK_SATCAT_RECORDS_URL,
        params={"GROUP": group, "FORMAT": "JSON"},
        timeout=120,
    )
    resp.raise_for_status()
    payload: Any = resp.json()
    if not isinstance(payload, list):
        raise ValueError(f"SATCAT group {group!r}: expected JSON list")
    keys: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("OBJECT_ID", ""))
        m = re.match(r"^(\d{4}-\d{3})", oid)
        if m:
            keys.add(m.group(1))
    return sorted(keys)


def _fetch_tles_via_intdes_launches(
    group: str,
    session: requests.Session,
    *,
    orig_hint: str,
) -> list[TLE]:
    launches = _launch_keys_from_satcat_group(group, session)
    if not launches:
        raise CelestrakGPUnchangedError(orig_hint)
    fetched_at = datetime.now(timezone.utc)
    by_norad: dict[int, TLE] = {}
    for idx, intdes in enumerate(launches, start=1):
        resp = session.get(
            CELESTRAK_GP_TLE_URL,
            params={"INTDES": intdes, "FORMAT": "tle"},
            timeout=120,
        )
        if resp.status_code == 403 and _gp_unchanged_body(resp.text):
            log.warning("INTDES=%r TLE download unchanged; skipping launch slice", intdes)
            continue
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or "no gp data found" in text.lower():
            continue
        chunk = parse_tle_text(text, source_group=group, fetched_at=fetched_at)
        for tle in chunk:
            by_norad[tle.norad_id] = tle
        if idx == 1 or idx % 50 == 0 or idx == len(launches):
            log.info(
                "INTDES fallback %r: %d/%d launches merged; %d unique TLEs",
                group,
                idx,
                len(launches),
                len(by_norad),
            )
    if not by_norad:
        raise CelestrakGPUnchangedError(orig_hint)
    log.info(
        "INTDES fallback complete for %r: %d TLEs at %s",
        group,
        len(by_norad),
        fetched_at.isoformat(),
    )
    return list(by_norad.values())


def parse_tle_text(text: str, source_group: str, fetched_at: datetime) -> list[TLE]:
    """
    Parse CelesTrak ``FORMAT=tle`` body (name + line1 + line2 per object).

    Returns:
        A list of :class:`TLE` rows.

    Raises:
        ValueError: If a triplet is malformed or epoch cannot be parsed.
    """
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    tles: list[TLE] = []
    i = 0
    while i + 2 < len(lines):
        name = lines[i].strip()
        line1 = lines[i + 1].rstrip()
        line2 = lines[i + 2].rstrip()
        i += 3
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            raise ValueError(textwrap.shorten(f"Malformed TLE near {name!r}: {line1!r}", 240))
        norad_id = int(line1[2:7])
        epoch = parse_tle_epoch_utc(line1)
        tles.append(
            TLE(
                name=name,
                norad_id=norad_id,
                line1=line1,
                line2=line2,
                epoch=epoch,
                source_group=source_group,
                fetched_at=fetched_at.astimezone(timezone.utc),
            )
        )
    if i != len(lines):
        raise ValueError("Incomplete TLE triplet at end of file")
    return tles


def parse_tle_epoch_utc(line1: str) -> datetime:
    """
    Parse the TLE epoch field on line 1 (columns 19--32, 1-based).

    Returns:
        Epoch as timezone-aware UTC :class:`~datetime.datetime`.
    """
    if len(line1) < 32:
        raise ValueError("Line 1 too short for epoch field")
    epoch_raw = line1[18:32].strip()
    yy = int(epoch_raw[0:2], 10)
    doy = int(epoch_raw[2:5], 10)
    frac = float(epoch_raw[5:])
    year = 2000 + yy if yy < 57 else 1900 + yy
    base = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return base + timedelta(days=frac)


def fetch_satcat_for_groups(
    groups: tuple[str, ...] | None = None,
    session: requests.Session | None = None,
) -> dict[int, SatcatRecord]:
    """
    Fetch SATCAT JSON for each ``GROUP`` and merge into one NORAD-keyed map.

    Uses ``https://celestrak.org/satcat/records.php`` with the same group
    labels as GP element lists (e.g. ``starlink``, ``stations``), matching
    catalog coverage to the configured TLE pulls.

    Returns:
        Mapping `` NORAD ID -> SatcatRecord`` (later groups override on duplicates).

    Raises:
        requests.RequestException: On transport failures.
        ValueError: If the HTTP payload is not a JSON list of records.
    """
    want = groups if groups is not None else TLE_SOURCE_GROUPS
    sess = session or requests.Session()
    merged: dict[int, SatcatRecord] = {}
    for group in want:
        params: dict[str, str] = {"GROUP": group, "FORMAT": "JSON"}
        log.info("Fetching SATCAT for GROUP=%r", group)
        resp = sess.get(CELESTRAK_SATCAT_RECORDS_URL, params=params, timeout=120)
        resp.raise_for_status()
        payload: Any = resp.json()
        if not isinstance(payload, list):
            raise ValueError(f"SATCAT group {group!r}: expected JSON list")
        for row in payload:
            if not isinstance(row, dict):
                continue
            rec = SatcatRecord.from_celestrak_api_row(row)
            merged[rec.norad_id] = rec
        log.info(
            "Fetched SATCAT GROUP=%r: %d rows (merge size now %d)",
            group,
            len(payload),
            len(merged),
        )
    log.info("SATCAT merge complete: %d unique NORAD IDs", len(merged))
    return merged


def fetch_satcat_single(
    norad_id: int,
    session: requests.Session | None = None,
) -> SatcatRecord | None:
    """
    Fetch a single SATCAT record via ``CATNR``.

    Returns:
        A :class:`SatcatRecord`, or ``None`` if CelesTrak reports no rows.

    Raises:
        requests.RequestException: On transport failures.
    """
    sess = session or requests.Session()
    log.info("Fetching SATCAT CATNR=%d", norad_id)
    resp = sess.get(
        CELESTRAK_SATCAT_RECORDS_URL,
        params={"CATNR": str(norad_id), "FORMAT": "JSON"},
        timeout=60,
    )
    resp.raise_for_status()
    payload: Any = resp.json()
    if not isinstance(payload, list) or not payload:
        log.info("SATCAT CATNR=%d: no records", norad_id)
        return None
    rec = SatcatRecord.from_celestrak_api_row(payload[0])
    log.info("Fetched SATCAT CATNR=%d (%s)", norad_id, rec.object_name)
    return rec
