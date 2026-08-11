from pathlib import Path

import psycopg

from app.config import settings


def main() -> None:
    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    with psycopg.connect(settings.database_url) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
            name text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now())""")
        for path in sorted(migrations.glob("*.sql")):
            if connection.execute("SELECT 1 FROM schema_migrations WHERE name=%s", (path.name,)).fetchone():
                continue
            connection.execute(path.read_text())
            connection.execute("INSERT INTO schema_migrations(name) VALUES(%s)", (path.name,))
            print(f"applied {path.name}")


if __name__ == "__main__":
    main()

