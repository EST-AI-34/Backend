from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.database import has_database

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


KST = ZoneInfo("Asia/Seoul")

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

    def list_metrics(self) -> list[dict]:
        if not self._should_use_database():
            return list(self._metrics)

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
                  metric.unit,
                  COALESCE(measurement.source_ref, measurement.source_type, 'database') AS source,
                  COALESCE(measurement.measured_at, metric.created_at) AS recorded_at
                FROM esg_metrics metric
                LEFT JOIN LATERAL (
                  SELECT value, source_type, source_ref, measured_at
                  FROM esg_measurements
                  WHERE metric_id = metric.id
                  ORDER BY measured_at DESC
                  LIMIT 1
                ) measurement ON true
                ORDER BY metric.created_at DESC
                """
            ).fetchall()
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

        with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
            festival = connection.execute(
                "SELECT id FROM festivals ORDER BY starts_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
            if not festival:
                raise RuntimeError("Cannot create ESG metric because no festival exists in the database.")

            metric = connection.execute(
                """
                INSERT INTO esg_metrics(festival_id, name, category, unit)
                VALUES (%s, %s, %s, %s)
                RETURNING id, festival_id, name, category, unit, created_at
                """,
                (
                    festival["id"],
                    payload["metric_name"],
                    CATEGORY_TO_DB[payload["category"]],
                    payload["unit"],
                ),
            ).fetchone()
            measurement = connection.execute(
                """
                INSERT INTO esg_measurements(festival_id, metric_id, value, source_type, source_ref, status)
                VALUES (%s, %s, %s, 'manual', %s, 'VALIDATED')
                RETURNING value, source_ref, measured_at
                """,
                (festival["id"], metric["id"], payload["value"], payload["source"]),
            ).fetchone()

        return {
            "id": str(metric["id"]),
            "festival_id": str(metric["festival_id"]),
            "category": DB_TO_CATEGORY[metric["category"]],
            "metric_name": metric["name"],
            "value": float(measurement["value"]),
            "unit": metric["unit"],
            "source": measurement["source_ref"],
            "recorded_at": measurement["measured_at"],
        }

    def save_ai_briefing(self, *, question: str, context: list[str], verified_result: dict[str, Any], answer: str) -> None:
        if not self._should_use_database():
            return

        with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
            festival = connection.execute(
                "SELECT id FROM festivals ORDER BY starts_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
            if not festival:
                return

            conversation = connection.execute(
                "INSERT INTO ai_conversations(festival_id, language) VALUES (%s, 'ko') RETURNING id",
                (festival["id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO ai_messages(
                  conversation_id,
                  question,
                  search_query,
                  retrieved_context,
                  verified_result,
                  answer,
                  safety_status,
                  model_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'ALLOWED', 'myalan-esg-briefing-v1')
                """,
                (
                    conversation["id"],
                    question,
                    "admin_esg_briefing",
                    Jsonb(context),
                    Jsonb(verified_result),
                    answer,
                ),
            )
            connection.commit()

    def _should_use_database(self) -> bool:
        return has_database() and psycopg is not None
