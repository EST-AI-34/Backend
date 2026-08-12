import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from app.core.config import settings
from app.core.database import has_database

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)


class InsightsRepository:
    _shared_recommendation_events: list[dict[str, Any]] = []

    def __init__(self) -> None:
        self._risk_briefs: dict[tuple[str, bool], dict[str, Any]] = {}
        self._recommendation_events = self._shared_recommendation_events

    def list_risk_signals(self, festival_id: str, include_resolved: bool = False) -> list[dict[str, Any]]:
        if not self._should_use_database():
            return self._fixture_risk_signals(festival_id, include_resolved)
        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                festival = self._find_festival(connection, festival_id)
                if not festival:
                    return []
                signals: list[dict[str, Any]] = []
                try:
                    signals.extend(self._ticket_signals(connection, festival["id"], include_resolved))
                except Exception as exc:
                    logger.warning("Risk ticket signal DB read failed; skipping ticket signals: %s", exc)
                if self._table_exists(connection, "program_sessions"):
                    try:
                        signals.extend(self._schedule_signals(connection, festival["id"]))
                    except Exception as exc:
                        logger.warning("Risk schedule signal DB read failed; skipping schedule signals: %s", exc)
                elif self._table_exists(connection, "programs"):
                    try:
                        signals.extend(self._program_update_signals(connection, festival["id"]))
                    except Exception as exc:
                        logger.warning("Risk program update signal DB read failed; skipping schedule signals: %s", exc)
                return signals
        except Exception as exc:  # pragma: no cover - live DB availability varies
            logger.warning("Risk signal DB read failed; using fixture fallback: %s", exc)
            return self._fixture_risk_signals(festival_id, include_resolved)

    def list_business_candidates(self, festival_id: str) -> list[dict[str, Any]] | None:
        if not self._should_use_database():
            return None
        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                rows = connection.execute(
                    """
                    SELECT
                      business.id::text AS id,
                      business.festival_id::text AS festival_id,
                      business.name,
                      business.category,
                      business.area_id::text AS location_id,
                      business.latitude::float8 AS latitude,
                      business.longitude::float8 AS longitude,
                      lower(business.operating_status) AS operating_status,
                      business.is_sponsored,
                      business.accessible,
                      business.esg_participating,
                      business.coupon_available,
                      business.description
                    FROM participating_businesses business
                    JOIN festivals festival ON festival.id = business.festival_id
                    WHERE (festival.code = %s OR festival.id::text = %s)
                      AND business.participation_status = 'APPROVED'
                      AND business.operating_status = 'OPEN'
                    ORDER BY business.created_at, business.id
                    """,
                    (festival_id, festival_id),
                ).fetchall()
        except Exception as exc:  # pragma: no cover
            logger.warning("Business candidate DB read failed; no DB candidates returned: %s", exc)
            return None
        return [dict(row) for row in rows]

    def get_risk_brief(self, festival_id: str, include_resolved: bool) -> dict[str, Any] | None:
        if not self._should_use_database():
            saved = self._risk_briefs.get((festival_id, include_resolved))
            return dict(saved) if saved else None
        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                row = connection.execute(
                    """
                    SELECT payload
                    FROM ai_risk_briefs
                    WHERE festival_code = %s AND include_resolved = %s
                    ORDER BY generated_at DESC
                    LIMIT 1
                    """,
                    (festival_id, include_resolved),
                ).fetchone()
        except Exception as exc:  # pragma: no cover
            logger.warning("Risk brief DB read failed; using local fallback: %s", exc)
            return None
        return dict(row["payload"]) if row else None

    def save_risk_brief(self, festival_id: str, include_resolved: bool, payload: dict[str, Any]) -> dict[str, Any]:
        self._risk_briefs[(festival_id, include_resolved)] = dict(payload)
        if not self._should_use_database():
            return dict(payload)
        try:
            with psycopg.connect(settings.database_url, prepare_threshold=None) as connection:
                connection.execute(
                    """
                    INSERT INTO ai_risk_briefs(festival_code, include_resolved, payload, source_hash, generated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (festival_code, include_resolved, source_hash)
                    DO UPDATE SET payload = EXCLUDED.payload, generated_at = EXCLUDED.generated_at
                    """,
                    (
                        festival_id,
                        include_resolved,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        self._source_hash(payload),
                        payload["generated_at"],
                    ),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Risk brief DB save failed; local result returned: %s", exc)
        return dict(payload)

    def log_recommendation_event(self, payload: dict[str, Any]) -> None:
        payload = {**payload, "created_at": payload.get("created_at") or datetime.now(KST)}
        self._recommendation_events.append(dict(payload))
        if not self._should_use_database():
            return
        try:
            with psycopg.connect(settings.database_url, prepare_threshold=None) as connection:
                connection.execute(
                    """
                    INSERT INTO business_recommendation_events(
                      festival_code, request_snapshot, response_snapshot, policy_version
                    )
                    VALUES (%s, %s::jsonb, %s::jsonb, %s)
                    """,
                    (
                        payload["festival_id"],
                        json.dumps(payload["request"], ensure_ascii=False, default=str),
                        json.dumps(payload["response"], ensure_ascii=False, default=str),
                        payload["policy_version"],
                    ),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Recommendation event DB save failed; continuing: %s", exc)

    def list_recommendation_events(self, festival_id: str, window_days: int = 7) -> list[dict[str, Any]]:
        if not self._should_use_database():
            return [
                dict(event)
                for event in self._recommendation_events
                if str(event.get("festival_id")) == str(festival_id)
            ]
        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                rows = connection.execute(
                    """
                    SELECT
                      festival_code AS festival_id,
                      request_snapshot AS request,
                      response_snapshot AS response,
                      policy_version,
                      created_at
                    FROM business_recommendation_events
                    WHERE festival_code = %s
                      AND created_at >= now() - (%s::text || ' days')::interval
                    ORDER BY created_at DESC
                    """,
                    (festival_id, window_days),
                ).fetchall()
        except Exception as exc:  # pragma: no cover
            logger.warning("Recommendation event DB read failed; using local events: %s", exc)
            return [
                dict(event)
                for event in self._recommendation_events
                if str(event.get("festival_id")) == str(festival_id)
            ]
        return [dict(row) for row in rows]

    def _find_festival(self, connection: Any, festival_id: str) -> dict[str, Any] | None:
        return connection.execute(
            "SELECT id FROM festivals WHERE code = %s OR id::text = %s LIMIT 1",
            (festival_id, festival_id),
        ).fetchone()

    def _table_exists(self, connection: Any, table_name: str) -> bool:
        row = connection.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table_name}",)).fetchone()
        if not row:
            return False
        if isinstance(row, dict):
            return bool(next(iter(row.values())))
        return bool(row[0])

    def _ticket_signals(self, connection: Any, festival_uuid: str, include_resolved: bool) -> list[dict[str, Any]]:
        status_filter = "" if include_resolved else "AND status NOT IN ('RESOLVED','CLOSED')"
        rows = connection.execute(
            f"""
            SELECT ticket_type, priority, count(*)::int AS value, max(updated_at) AS source_updated_at
            FROM ops_tickets
            WHERE festival_id = %s
              {status_filter}
              AND priority IN ('HIGH','EMERGENCY')
            GROUP BY ticket_type, priority
            """,
            (festival_uuid,),
        ).fetchall()
        signals: list[dict[str, Any]] = []
        for row in rows:
            signal_type = "unresolved_safety_complaints" if row["ticket_type"] == "COMPLAINT" else "crowding"
            signals.append(
                {
                    "type": signal_type,
                    "value": row["value"],
                    "threshold": 0,
                    "source_updated_at": row["source_updated_at"],
                }
            )
        return signals

    def _schedule_signals(self, connection: Any, festival_uuid: str) -> list[dict[str, Any]]:
        row = connection.execute(
            """
            SELECT count(*)::int AS value, max(updated_at) AS source_updated_at
            FROM program_sessions
            WHERE festival_id = %s
              AND updated_at > created_at + interval '1 minute'
            """,
            (festival_uuid,),
        ).fetchone()
        if not row or row["value"] == 0:
            return []
        return [
            {
                "type": "schedule_change",
                "value": row["value"],
                "threshold": 0,
                "source_updated_at": row["source_updated_at"],
            }
        ]

    def _program_update_signals(self, connection: Any, festival_uuid: str) -> list[dict[str, Any]]:
        row = connection.execute(
            """
            SELECT count(*)::int AS value, max(updated_at) AS source_updated_at
            FROM programs
            WHERE festival_id = %s
              AND updated_at > created_at + interval '1 minute'
            """,
            (festival_uuid,),
        ).fetchone()
        if not row or row["value"] == 0:
            return []
        return [
            {
                "type": "schedule_change",
                "value": row["value"],
                "threshold": 0,
                "source_updated_at": row["source_updated_at"],
            }
        ]

    def _fixture_risk_signals(self, festival_id: str, include_resolved: bool) -> list[dict[str, Any]]:
        if str(festival_id) not in {"1", "EST34-2026"}:
            return []
        now = datetime.now(KST)
        return [
            {"type": "crowding", "value": 86, "threshold": 80, "source_updated_at": now},
            {"type": "unresolved_safety_complaints", "value": 2, "threshold": 1, "source_updated_at": now},
            {"type": "staffing_gap", "value": 1, "threshold": 0, "source_updated_at": now},
        ]

    def _should_use_database(self) -> bool:
        return has_database() and psycopg is not None

    def _source_hash(self, payload: dict[str, Any]) -> str:
        import hashlib

        raw = json.dumps(payload.get("evidence", []), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
