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
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations(name) VALUES(%s)", (path.name,))
            print(f"applied {path.name}")


if __name__ == "__main__":
    main()
