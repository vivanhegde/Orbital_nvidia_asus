"""Typed records for orbital catalog and space weather data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TLE:
    """Two-line element set with parsed epoch and metadata."""

    name: str
    norad_id: int
    line1: str
    line2: str
    epoch: datetime
    source_group: str
    fetched_at: datetime

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (UTC ISO datetimes)."""
        return {
            "name": self.name,
            "norad_id": self.norad_id,
            "line1": self.line1,
            "line2": self.line2,
            "epoch": _dt_iso(self.epoch),
            "source_group": self.source_group,
            "fetched_at": _dt_iso(self.fetched_at),
        }

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> TLE:
        """Restore a ``TLE`` from :meth:`to_json_dict` output."""
        return TLE(
            name=data["name"],
            norad_id=int(data["norad_id"]),
            line1=data["line1"],
            line2=data["line2"],
            epoch=_parse_dt(data["epoch"]),
            source_group=data["source_group"],
            fetched_at=_parse_dt(data["fetched_at"]),
        )


@dataclass(frozen=True)
class SatcatRecord:
    """CelesTrak SATCAT JSON record mapped to typed fields."""

    object_name: str
    norad_id: int
    country: str
    launch_date: datetime | None
    decay_date: datetime | None
    object_type: str
    rcs_size: float | None
    period: float | None
    inclination: float | None

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (UTC ISO datetimes)."""
        return {
            "object_name": self.object_name,
            "norad_id": self.norad_id,
            "country": self.country,
            "launch_date": _dt_iso(self.launch_date) if self.launch_date else None,
            "decay_date": _dt_iso(self.decay_date) if self.decay_date else None,
            "object_type": self.object_type,
            "rcs_size": self.rcs_size,
            "period": self.period,
            "inclination": self.inclination,
        }

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> SatcatRecord:
        """Restore a ``SatcatRecord`` from :meth:`to_json_dict` output."""
        return SatcatRecord(
            object_name=data["object_name"],
            norad_id=int(data["norad_id"]),
            country=data["country"],
            launch_date=_parse_dt(data["launch_date"]) if data.get("launch_date") else None,
            decay_date=_parse_dt(data["decay_date"]) if data.get("decay_date") else None,
            object_type=data["object_type"],
            rcs_size=float(data["rcs_size"]) if data.get("rcs_size") is not None else None,
            period=float(data["period"]) if data.get("period") is not None else None,
            inclination=float(data["inclination"]) if data.get("inclination") is not None else None,
        )

    @staticmethod
    def from_celestrak_api_row(row: dict[str, Any]) -> SatcatRecord:
        """Build from a single object in CelesTrak ``records.php`` JSON."""
        decay_raw = row.get("DECAY_DATE") or ""
        launch_raw = row.get("LAUNCH_DATE") or ""
        rcs = parsed_float(row.get("RCS"))
        period = parsed_float(row.get("PERIOD"))
        inc = parsed_float(row.get("INCLINATION"))
        return SatcatRecord(
            object_name=str(row.get("OBJECT_NAME", "")),
            norad_id=int(row["NORAD_CAT_ID"]),
            country=str(row.get("OWNER", "")),
            launch_date=parse_date_only(launch_raw),
            decay_date=parse_date_only(decay_raw) if decay_raw.strip() else None,
            object_type=str(row.get("OBJECT_TYPE", "")),
            rcs_size=rcs,
            period=period,
            inclination=inc,
        )


@dataclass(frozen=True)
class SpaceWeatherSnapshot:
    """NOAA SWPC-driven space weather metrics for propagation inputs."""

    kp_index: float
    kp_trend: tuple[float, ...]
    xray_flux_short: float
    xray_class: str
    geomag_storm_level: str
    fetched_at: datetime

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (UTC ISO datetimes)."""
        return {
            "kp_index": self.kp_index,
            "kp_trend": list(self.kp_trend),
            "xray_flux_short": self.xray_flux_short,
            "xray_class": self.xray_class,
            "geomag_storm_level": self.geomag_storm_level,
            "fetched_at": _dt_iso(self.fetched_at),
        }

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> SpaceWeatherSnapshot:
        """Restore from :meth:`to_json_dict` output."""
        return SpaceWeatherSnapshot(
            kp_index=float(data["kp_index"]),
            kp_trend=tuple(float(x) for x in data["kp_trend"]),
            xray_flux_short=float(data["xray_flux_short"]),
            xray_class=str(data["xray_class"]),
            geomag_storm_level=str(data["geomag_storm_level"]),
            fetched_at=_parse_dt(data["fetched_at"]),
        )


def parsed_float(value: Any) -> float | None:
    """Parse API float or ``None``; returns ``None`` for null or invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_date_only(raw: str) -> datetime | None:
    """Parse ``YYYY-MM-DD`` to UTC midnight, or ``None`` if empty/invalid."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
        if d.tzinfo is None:
            return d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except ValueError:
        return None


def _dt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(raw: str | Any) -> datetime:
    """Parse ISO datetime string to aware UTC."""
    from datetime import datetime as dt_mod

    if isinstance(raw, dt_mod):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = dt_mod.fromisoformat(s)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
