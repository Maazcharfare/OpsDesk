#!/usr/bin/env python3
"""Restore a verified SQLite backup without silently overwriting live data."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def integrity(path: Path) -> None:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"Refusing restore; integrity_check failed: {result}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="Verified backup file")
    parser.add_argument("destination", help="Destination DB path")
    parser.add_argument("--replace", action="store_true", help="Allow replacement of destination (make a backup first)")
    args = parser.parse_args()
    source, dest = Path(args.backup).expanduser().resolve(), Path(args.destination).expanduser().resolve()
    if not source.is_file():
        parser.error(f"Backup does not exist: {source}")
    if source == dest:
        parser.error("Backup and destination must be different files")
    if dest.exists() and not args.replace:
        parser.error(f"Destination exists; refusing to overwrite: {dest}. Use --replace only after a separate backup.")
    integrity(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".restore-tmp")
    try:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(tmp)) as dst:
                src.backup(dst)
        integrity(tmp)
        if dest.exists() and args.replace:
            safety = dest.with_name(dest.name + ".pre-restore.bak")
            if safety.exists():
                parser.error(f"Safety backup already exists: {safety}")
            dest.replace(safety)
            print(f"Previous destination preserved at: {safety}")
        tmp.replace(dest)
        dest.chmod(0o600)
        print(f"Restore verified: {dest}")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
