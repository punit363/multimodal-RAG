"""Copy a stopped, current-schema SQLite registry into an empty PostgreSQL database."""

import argparse
import os
import sqlite3
from pathlib import Path

from app.database import SCHEMA_VERSION
from app.postgres_database import Connection, init_db


TABLES = (
    "conversations", "messages", "folders", "documents", "source_sets",
    "source_set_documents", "shares", "share_comments", "usage_windows",
    "audit_events", "ingestion_jobs", "members",
)


def migrate(sqlite_path: Path, postgres_url: str) -> dict[str, int]:
    """Copy every registry table atomically, refusing partial or nonempty targets."""
    if not sqlite_path.is_file():
        raise ValueError("SQLite source does not exist.")
    uri = f"file:{sqlite_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as source:
        source.row_factory = sqlite3.Row
        version = source.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(f"SQLite source must be schema version {SCHEMA_VERSION}; found {version}.")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite source failed integrity check.")
        init_db(postgres_url, SCHEMA_VERSION)
        counts = {}
        with Connection(postgres_url) as target:
            target.execute("SELECT pg_advisory_xact_lock(80973194)")
            for table in TABLES:
                if target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                    raise ValueError("PostgreSQL target must have empty registry tables.")
            for table in TABLES:
                columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                if not columns:
                    raise ValueError(f"SQLite source is missing {table}.")
                rows = source.execute(f"SELECT * FROM {table}").fetchall()
                sql = (f"INSERT INTO {table} ({', '.join(columns)}) "
                       f"VALUES ({', '.join('?' for _ in columns)})")
                for row in rows:
                    target.execute(sql, tuple(row))
                count = target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count != len(rows):
                    raise RuntimeError(f"Row count mismatch for {table}.")
                counts[table] = count
            target.execute("""SELECT setval(pg_get_serial_sequence('audit_events', 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM audit_events), 1), 1),
                EXISTS(SELECT 1 FROM audit_events))""")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--postgres-url", default=os.getenv("RAG_DATABASE_URL"))
    args = parser.parse_args()
    if not args.postgres_url:
        parser.error("Set RAG_DATABASE_URL or provide --postgres-url.")
    print(migrate(args.sqlite, args.postgres_url))


if __name__ == "__main__":
    main()
