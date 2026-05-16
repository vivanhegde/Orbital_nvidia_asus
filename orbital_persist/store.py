"""EventStore: SQLite read/write API for conjunction persistence."""

from __future__ import annotations

import json
import logging
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orbital_persist.db import connect, run_migrations
from orbital_persist.ids import stable_event_id
from orbital_persist.models import ConjunctionEventRecord, PcSnapshotRow, VerdictRecord

if TYPE_CHECKING:
    from orbital_engine.models import ConjunctionCandidate


def _bootstrap_repo_paths() -> None:
    root = Path(__file__).resolve().parent.parent
    od = root / "orbital_data"
    if od.is_dir() and str(od) not in sys.path:
        sys.path.insert(0, str(od))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_bootstrap_repo_paths()

from models import SpaceWeatherSnapshot  # noqa: E402

log = logging.getLogger(__name__)


def _parse_dt(s: str) -> datetime:
    raw = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sw_json(blob: str | None) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


class EventStore:
    """SQLite-backed store for conjunction screening history and verdicts."""

    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._conn = connect(self._path)
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        run_migrations(self._conn, migrations_dir)
        log.info("EventStore ready at %s", self._path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record_screening_pass(
        self,
        candidates: list[ConjunctionCandidate],
        space_weather: SpaceWeatherSnapshot,
        covariance_inflation: float,
        now: datetime,
    ) -> None:
        """Upsert events and append Pc snapshots for each candidate (Pc uses ``covariance_inflation``)."""
        from orbital_engine.pc import compute_pc

        now = now.astimezone(timezone.utc)
        sw_blob_detect = json.dumps(space_weather.to_json_dict())
        sw_dict: dict[str, Any] = space_weather.to_json_dict()
        sw_snap_json = json.dumps(sw_dict)

        with self._lock:
            cur = self._conn.cursor()
            for c in candidates:
                pc_computed = compute_pc(
                    c.obj1_state_at_tca,
                    c.obj2_state_at_tca,
                    covariance_inflation=covariance_inflation,
                )
                eid = stable_event_id(c.obj1_norad_id, c.obj2_norad_id, c.tca)
                if c.obj1_norad_id <= c.obj2_norad_id:
                    n1, name1 = c.obj1_norad_id, c.obj1_name
                    n2, name2 = c.obj2_norad_id, c.obj2_name
                else:
                    n1, name1 = c.obj2_norad_id, c.obj2_name
                    n2, name2 = c.obj1_norad_id, c.obj1_name

                cur.execute("SELECT 1 FROM conjunction_events WHERE event_id = ?", (eid,))
                exists = cur.fetchone() is not None

                if not exists:
                    cur.execute(
                        """
                        INSERT INTO conjunction_events (
                          event_id, obj1_norad_id, obj1_name, obj2_norad_id, obj2_name,
                          first_detected_at, last_seen_at, tca, initial_miss_distance_km,
                          initial_pc, relative_velocity_km_s, status, space_weather_at_detection
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'monitoring', ?)
                        """,
                        (
                            eid,
                            n1,
                            name1,
                            n2,
                            name2,
                            now.isoformat(),
                            now.isoformat(),
                            c.tca.astimezone(timezone.utc).isoformat(),
                            c.miss_distance_km,
                            pc_computed,
                            c.relative_velocity_km_s,
                            sw_blob_detect,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE conjunction_events
                        SET last_seen_at = ?, tca = ?
                        WHERE event_id = ?
                        """,
                        (
                            now.isoformat(),
                            c.tca.astimezone(timezone.utc).isoformat(),
                            eid,
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO pc_snapshots (
                      event_id, snapshot_at, pc, miss_distance_km,
                      covariance_inflation, kp_index, space_weather_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid,
                        now.isoformat(),
                        pc_computed,
                        c.miss_distance_km,
                        covariance_inflation,
                        space_weather.kp_index,
                        sw_snap_json,
                    ),
                )

            self._conn.commit()

    def get_event(self, event_id: str) -> ConjunctionEventRecord | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM conjunction_events WHERE event_id = ?", (event_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            d = dict(zip(cols, row))
            return self._row_to_event(d)

    def _row_to_event(self, d: dict[str, Any]) -> ConjunctionEventRecord:
        return ConjunctionEventRecord(
            event_id=str(d["event_id"]),
            obj1_norad_id=int(d["obj1_norad_id"]),
            obj1_name=str(d["obj1_name"]),
            obj2_norad_id=int(d["obj2_norad_id"]),
            obj2_name=str(d["obj2_name"]),
            first_detected_at=_parse_dt(str(d["first_detected_at"])),
            last_seen_at=_parse_dt(str(d["last_seen_at"])),
            tca=_parse_dt(str(d["tca"])),
            initial_miss_distance_km=float(d["initial_miss_distance_km"]),
            initial_pc=float(d["initial_pc"]),
            relative_velocity_km_s=float(d["relative_velocity_km_s"]),
            status=str(d["status"]),
            space_weather_at_detection=_sw_json(
                d.get("space_weather_at_detection") if d.get("space_weather_at_detection") else None
            ),
        )

    def get_pc_history(self, event_id: str, hours_back: int = 48) -> list[PcSnapshotRow]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT snapshot_id, event_id, snapshot_at, pc, miss_distance_km,
                       covariance_inflation, kp_index, space_weather_snapshot
                FROM pc_snapshots
                WHERE event_id = ? AND snapshot_at >= ?
                ORDER BY snapshot_at ASC
                """,
                (event_id, cutoff.isoformat()),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out: list[PcSnapshotRow] = []
        for tup in rows:
            d = dict(zip(cols, tup))
            out.append(
                PcSnapshotRow(
                    snapshot_id=int(d["snapshot_id"]),
                    event_id=str(d["event_id"]),
                    snapshot_at=_parse_dt(str(d["snapshot_at"])),
                    pc=float(d["pc"]),
                    miss_distance_km=float(d["miss_distance_km"]),
                    covariance_inflation=float(d["covariance_inflation"]),
                    kp_index=float(d["kp_index"]) if d.get("kp_index") is not None else None,
                    space_weather_snapshot=_sw_json(
                        d.get("space_weather_snapshot") if isinstance(d.get("space_weather_snapshot"), str) else None
                    ),
                )
            )
        return out

    def get_latest_pc_snapshot(self, event_id: str) -> PcSnapshotRow | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT snapshot_id, event_id, snapshot_at, pc, miss_distance_km,
                       covariance_inflation, kp_index, space_weather_snapshot
                FROM pc_snapshots
                WHERE event_id = ?
                ORDER BY snapshot_at DESC
                LIMIT 1
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            colnames = [d[0] for d in cur.description]
            d = dict(zip(colnames, row))
        return PcSnapshotRow(
            snapshot_id=int(d["snapshot_id"]),
            event_id=str(d["event_id"]),
            snapshot_at=_parse_dt(str(d["snapshot_at"])),
            pc=float(d["pc"]),
            miss_distance_km=float(d["miss_distance_km"]),
            covariance_inflation=float(d["covariance_inflation"]),
            kp_index=float(d["kp_index"]) if d.get("kp_index") is not None else None,
            space_weather_snapshot=_sw_json(
                d.get("space_weather_snapshot") if isinstance(d.get("space_weather_snapshot"), str) else None
            ),
        )

    def query_events_for_asset(
        self,
        norad_id: int,
        limit: int = 20,
    ) -> list[ConjunctionEventRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT * FROM conjunction_events
                WHERE obj1_norad_id = ? OR obj2_norad_id = ?
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (norad_id, norad_id, limit),
            )
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
        return [self._row_to_event(dict(zip(colnames, r))) for r in rows]

    def query_recent_events(
        self,
        limit: int = 50,
        status: str | None = None,
    ) -> list[ConjunctionEventRecord]:
        with self._lock:
            cur = self._conn.cursor()
            if status:
                cur.execute(
                    """
                    SELECT * FROM conjunction_events
                    WHERE status = ?
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM conjunction_events
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
        return [self._row_to_event(dict(zip(colnames, r))) for r in rows]

    def record_verdict(
        self,
        event_id: str,
        verdict_type: str,
        reasoning: str,
        plan: dict[str, Any] | None = None,
    ) -> str:
        vid = uuid.uuid4().hex
        issued = datetime.now(timezone.utc).isoformat()
        plan_s = json.dumps(plan) if plan is not None else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO verdicts (
                  verdict_id, event_id, issued_at, verdict_type, reasoning,
                  plan_json, operator_decision, operator_decided_at, operator_notes
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (vid, event_id, issued, verdict_type, reasoning, plan_s),
            )
            self._conn.commit()
        return vid

    def list_pending_verdicts(self) -> list[VerdictRecord]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT * FROM verdicts
                WHERE operator_decision IS NULL OR operator_decision = 'pending'
                ORDER BY issued_at DESC
                """
            )
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
        return [self._row_to_verdict(dict(zip(colnames, r))) for r in rows]

    def _row_to_verdict(self, d: dict[str, Any]) -> VerdictRecord:
        pj = d.get("plan_json")
        plan: dict[str, Any] | None
        if pj:
            try:
                plan = json.loads(str(pj))
                if not isinstance(plan, dict):
                    plan = {"raw": plan}
            except json.JSONDecodeError:
                plan = None
        else:
            plan = None
        od = d.get("operator_decided_at")
        return VerdictRecord(
            verdict_id=str(d["verdict_id"]),
            event_id=str(d["event_id"]),
            issued_at=_parse_dt(str(d["issued_at"])),
            verdict_type=str(d["verdict_type"]),
            reasoning=str(d["reasoning"]),
            plan_json=plan,
            operator_decision=str(d["operator_decision"]) if d.get("operator_decision") else None,
            operator_decided_at=_parse_dt(str(od)) if od else None,
            operator_notes=str(d["operator_notes"]) if d.get("operator_notes") else None,
        )

    def get_verdict(self, verdict_id: str) -> VerdictRecord | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM verdicts WHERE verdict_id = ?", (verdict_id,))
            row = cur.fetchone()
            if not row:
                return None
            colnames = [d[0] for d in cur.description]
            return self._row_to_verdict(dict(zip(colnames, row)))

    def update_operator_decision(
        self,
        verdict_id: str,
        decision: str,
        notes: str | None = None,
    ) -> bool:
        decided = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE verdicts
                SET operator_decision = ?, operator_decided_at = ?, operator_notes = ?
                WHERE verdict_id = ?
                """,
                (decision, decided, notes, verdict_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def expire_stale_events(self, older_than_hours: int = 6) -> int:
        threshold = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE conjunction_events
                SET status = 'expired'
                WHERE status NOT IN ('dismissed', 'resolved', 'expired')
                  AND last_seen_at < ?
                """,
                (threshold,),
            )
            self._conn.commit()
            return int(cur.rowcount)
