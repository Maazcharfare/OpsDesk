#!/usr/bin/env python3
"""Create a consistent SQLite backup and verify its integrity."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="opsdesk.db", help="Source SQLite database")
    parser.add_argument("--output-dir", default="backups", help="Directory for backup files")
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    if not source.is_file():
        parser.error(f"Source database does not exist: {source}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"opsdesk-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}.db"
    try:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        with closing(sqlite3.connect(target)) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                target.unlink(missing_ok=True)
                raise RuntimeError(f"SQLite integrity_check failed: {result}")
        target.chmod(0o600)
        print(f"Backup verified: {target}")
        print("Store an additional encrypted/off-host copy and periodically test restoration.")
        return 0
    except Exception:
        target.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
