"""Dry-run and apply the local operational retention policy."""

import argparse
import json
from pathlib import Path

from app import database


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or apply SQLite retention cleanup.")
    parser.add_argument("--database", default=database.DB_PATH, help="SQLite registry path")
    parser.add_argument("--audit-days", type=int, default=90, help="Retain audit events for this many days")
    parser.add_argument("--apply", action="store_true", help="Delete counted records (default is dry run)")
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error("SQLite registry does not exist; refusing to create an empty database.")
    database.DB_PATH = args.database
    result = database.retention_summary(audit_days=args.audit_days, apply=args.apply)
    print(json.dumps({"mode": "applied" if args.apply else "dry_run", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
