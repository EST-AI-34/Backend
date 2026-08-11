from collections.abc import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.core.config import settings


def has_database() -> bool:
    return bool(settings.database_url.strip())


def get_connection() -> Iterator[Connection]:
    with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
        yield connection
