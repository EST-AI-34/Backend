import re
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

CATEGORY_TO_DB = {
    "environment": "E",
    "social": "S",
    "governance": "G",
}

DB_TO_CATEGORY = {value: key for key, value in CATEGORY_TO_DB.items()}


class ESGRepository:
    def __init__(self) -> None:
        now = datetime.now(KST)
        self._metrics = [
            {
                "id": 1,
                "festival_id": 1,
                "category": "environment",
                "metric_name": "Mobile leaflet views",
                "value": 1240,
                "unit": "views",
                "source": "Visitor QR access log",
                "recorded_at": now,
            },
            {
                "id": 2,
                "festival_id": 1,
                "category": "social",
                "metric_name": "Local coupon uses",
                "value": 155,
                "unit": "uses",
                "source": "Coupon usage log",
                "recorded_at": now,
            },
            {
                "id": 3,
                "festival_id": 1,
                "category": "governance",
                "metric_name": "Verified operation updates",
                "value": 18,
                "unit": "updates",
                "source": "Admin approval history",
                "recorded_at": now,
            },
        ]
        self._briefings: dict[tuple[str, str], dict[str, Any]] = {}

    def list_metrics(self) -> list[dict]:
        if not self._should_use_database():
            return list(self._metrics)

        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                rows = connection.execute(
                    """
                    SELECT
                      metric.id::text AS id,
                      metric.festival_id::text AS festival_id,
                      CASE metric.category
                        WHEN 'E' THEN 'environment'
                        WHEN 'S' THEN 'social'
                        WHEN 'G' THEN 'governance'
                        ELSE lower(metric.category)
                      END AS category,
                      metric.name AS metric_name,
                      COALESCE(measurement.value, 0)::float8 AS value,
                      COALESCE(version.unit, '') AS unit,
                      COALESCE(measurement.source_ref, measurement.source_type, 'database') AS source,
                      COALESCE(measurement.measured_at, metric.created_at) AS recorded_at
                    FROM esg_metrics metric
                    LEFT JOIN LATERAL (
                      SELECT id, unit
                      FROM esg_metric_versions
                      WHERE metric_id = metric.id
                      ORDER BY version_no DESC
                      LIMIT 1
                    ) version ON true
                    LEFT JOIN LATERAL (
                      SELECT value, source_type, source_ref, measured_at
                      FROM esg_measurements
                      WHERE metric_version_id = version.id
                      ORDER BY measured_at DESC
                      LIMIT 1
                    ) measurement ON true
                    ORDER BY metric.created_at DESC
                    """
                ).fetchall()
        except Exception as exc:  # pragma: no cover
            logger.warning("ESG metric DB read failed; using in-memory fixture: %s", exc)
            return list(self._metrics)
        return [dict(row) for row in rows]

    def create_metric(self, payload: dict) -> dict:
        if not self._should_use_database():
            metric = {
                "id": len(self._metrics) + 1,
                "festival_id": 1,
                "recorded_at": datetime.now(KST),
                **payload,
            }
            self._metrics.append(metric)
            return metric

        try:
            with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
                festival = connection.execute(
                    "SELECT id FROM festivals ORDER BY starts_at DESC, created_at DESC LIMIT 1"
                ).fetchone()
                if not festival:
                    raise RuntimeError("Cannot create ESG metric because no festival exists in the database.")

                actor = connection.execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
                if not actor:
                    raise RuntimeError("Cannot create ESG metric because no user exists in the database.")

                metric = connection.execute(
                    """
                    INSERT INTO esg_metrics(festival_id, name, category, created_by)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, festival_id, name, category, created_at
                    """,
                    (festival["id"], payload["metric_name"], CATEGORY_TO_DB[payload["category"]], actor["id"]),
                ).fetchone()
                version = connection.execute(
                    """
                    INSERT INTO esg_metric_versions(
                      metric_id, version_no, formula, unit, source_requirements, created_by
                    )
                    VALUES (%s, 1, 'manual', %s, '{}'::jsonb, %s)
                    RETURNING id, unit
                    """,
                    (metric["id"], payload["unit"], actor["id"]),
                ).fetchone()
                measurement = connection.execute(
                    """
                    INSERT INTO esg_measurements(
                      festival_id, metric_version_id, value, source_type, source_ref,
                      dedupe_key, measured_at, status, created_by
                    )
                    VALUES (%s, %s, %s, 'manual', %s, %s, now(), 'APPROVED', %s)
                    RETURNING value, source_ref, measured_at
                    """,
                    (
                        festival["id"],
                        version["id"],
                        payload["value"],
                        payload["source"],
                        f"manual:{metric['id']}",
                        actor["id"],
                    ),
                ).fetchone()
        except Exception as exc:  # pragma: no cover
            logger.warning("ESG metric DB write failed; using in-memory fixture: %s", exc)
            metric = {
                "id": len(self._metrics) + 1,
                "festival_id": 1,
                "recorded_at": datetime.now(KST),
                **payload,
            }
            self._metrics.append(metric)
            return metric

        return {
            "id": str(metric["id"]),
            "festival_id": str(metric["festival_id"]),
            "category": DB_TO_CATEGORY[metric["category"]],
            "metric_name": metric["name"],
            "value": float(measurement["value"]),
            "unit": version["unit"],
            "source": measurement["source_ref"],
            "recorded_at": measurement["measured_at"],
        }

    def get_latest_briefing(self, festival_code: str, focus: str = "esg") -> dict[str, Any] | None:
        if not self._should_use_database():
            briefing = self._briefings.get((festival_code, focus))
            return dict(briefing) if briefing else None

        with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
            row = connection.execute(
                """
                SELECT
                  message.verified_result,
                  message.answer AS allen_comment,
                  message.created_at AS generated_at
                FROM ai_messages message
                JOIN ai_conversations conversation ON conversation.id = message.conversation_id
                JOIN festivals festival ON festival.id = conversation.festival_id
                WHERE festival.code = %s
                  AND message.question = %s
                  AND message.safety_status = 'ALLOWED'
                ORDER BY message.created_at DESC
                LIMIT 1
                """,
                (festival_code, self._briefing_question(focus)),
            ).fetchone()
        if not row:
            return None
        if not self._is_usable_briefing(row["allen_comment"]):
            return None
        verified_result = row.get("verified_result") or {}
        if not isinstance(verified_result, dict):
            return None
        return {
            **verified_result,
            "allen_comment": row["allen_comment"],
            "generated_at": row["generated_at"],
        }

    def save_briefing(self, festival_code: str, focus: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(KST)
        row = {
            "summary": payload["summary"],
            "allen_comment": payload["allen_comment"],
            "metric_label": payload["metric_label"],
            "metric_value": payload["metric_value"],
            "status": payload["status"],
            "sources": payload["sources"],
            "provider": payload.get("provider", "allen"),
            "context_snapshot": payload.get("context_snapshot", []),
            "generated_at": payload.get("generated_at", now),
        }

        if not self._should_use_database():
            self._briefings[(festival_code, focus)] = row
            return dict(row)

        verified_result = {
            "summary": row["summary"],
            "metric_label": row["metric_label"],
            "metric_value": row["metric_value"],
            "status": row["status"],
            "sources": row["sources"],
            "provider": row["provider"],
        }

        with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
            existing = connection.execute(
                """
                SELECT message.id
                FROM ai_messages message
                JOIN ai_conversations conversation ON conversation.id = message.conversation_id
                JOIN festivals festival ON festival.id = conversation.festival_id
                WHERE festival.code = %s
                  AND message.question = %s
                ORDER BY message.created_at DESC
                LIMIT 1
                """,
                (festival_code, self._briefing_question(focus)),
            ).fetchone()
            if existing:
                saved = connection.execute(
                    """
                    UPDATE ai_messages
                    SET
                      search_query = %s,
                      retrieved_context = %s::jsonb,
                      verified_result = %s::jsonb,
                      answer = %s,
                      safety_status = 'ALLOWED',
                      model_version = 'allen-esg-briefing-v1',
                      created_at = %s
                    WHERE id = %s
                    RETURNING verified_result, answer AS allen_comment, created_at AS generated_at
                    """,
                    (
                        "admin esg briefing",
                        json_dumps(row["context_snapshot"]),
                        json_dumps(verified_result),
                        row["allen_comment"],
                        row["generated_at"],
                        existing["id"],
                    ),
                ).fetchone()
                saved_result = saved["verified_result"]
                return {
                    **saved_result,
                    "allen_comment": saved["allen_comment"],
                    "generated_at": saved["generated_at"],
                }

            conversation = connection.execute(
                """
                WITH selected_festival AS (
                  SELECT id FROM festivals WHERE code = %s LIMIT 1
                )
                INSERT INTO ai_conversations(festival_id, language)
                SELECT id, 'ko' FROM selected_festival
                RETURNING id
                """,
                (festival_code,),
            ).fetchone()
            if not conversation:
                raise RuntimeError(f"Festival code {festival_code} was not found.")

            saved = connection.execute(
                """
                INSERT INTO ai_messages(
                  conversation_id,
                  question,
                  search_query,
                  retrieved_context,
                  verified_result,
                  answer,
                  safety_status,
                  model_version,
                  created_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, 'ALLOWED', 'allen-esg-briefing-v1', %s)
                RETURNING verified_result, answer AS allen_comment, created_at AS generated_at
                """,
                (
                    conversation["id"],
                    self._briefing_question(focus),
                    "admin esg briefing",
                    json_dumps(row["context_snapshot"]),
                    json_dumps(verified_result),
                    row["allen_comment"],
                    row["generated_at"],
                ),
            ).fetchone()

        saved_result = saved["verified_result"]
        return {
            **saved_result,
            "allen_comment": saved["allen_comment"],
            "generated_at": saved["generated_at"],
        }

    def _should_use_database(self) -> bool:
        return has_database() and psycopg is not None

    def _briefing_question(self, focus: str) -> str:
        return f"admin:{focus}:one-line-briefing"

    def _is_usable_briefing(self, value: str | None) -> bool:
        if not value or len(value.strip()) < 12:
            return False
        return re.search(r"\d\.$", value.strip()) is None


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
