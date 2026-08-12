from pathlib import Path

import psycopg

from app.core.config import settings


def main() -> None:
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is required. Use the Supabase Postgres connection string "
            "with sslmode=require."
        )

    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    with psycopg.connect(settings.database_url, prepare_threshold=None) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in sorted(migrations.glob("*.sql")):
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name=%s",
                (path.name,),
            ).fetchone()
            if applied:
                continue
            if path.name == "001_init.sql" and _existing_initial_schema(connection):
                connection.execute("INSERT INTO schema_migrations(name) VALUES(%s)", (path.name,))
                print(f"marked existing {path.name}")
                continue
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations(name) VALUES(%s)", (path.name,))
            print(f"applied {path.name}")


def _existing_initial_schema(connection: psycopg.Connection) -> bool:
    required_tables = [
        "organizations",
        "users",
        "memberships",
        "festivals",
        "festival_areas",
        "facilities",
        "programs",
        "program_sessions",
        "content_items",
        "content_versions",
        "announcements",
        "ops_tickets",
        "visitor_sessions",
        "ai_conversations",
        "ai_messages",
        "surveys",
        "esg_metrics",
        "esg_metric_versions",
        "esg_measurements",
        "audit_logs",
    ]
    row = connection.execute(
        """
        SELECT bool_and(to_regclass('public.' || table_name) IS NOT NULL) AS initialized
        FROM unnest(%s::text[]) AS required(table_name)
        """,
        (required_tables,),
    ).fetchone()
    return bool(row and row[0])


if __name__ == "__main__":
    main()
