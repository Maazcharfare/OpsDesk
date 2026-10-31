import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def make_database(path: Path, title: str) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE tickets (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        db.execute("INSERT INTO tickets(title) VALUES (?)", (title,))
        db.commit()


def run_script(
    script: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    destination = tmp_path / "restored.db"
    make_database(source, "Preserved ticket")

    backup_result = run_script(
        "backup_db.py", "--source", str(source), "--output-dir", str(backup_dir)
    )
    assert backup_result.returncode == 0, backup_result.stderr
    backup_files = list(backup_dir.glob("opsdesk-*.db"))
    assert len(backup_files) == 1

    restore_result = run_script("restore_db.py", str(backup_files[0]), str(destination))
    assert restore_result.returncode == 0, restore_result.stderr
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("SELECT title FROM tickets").fetchone()[0] == "Preserved ticket"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_names_do_not_collide_when_created_in_quick_succession(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    make_database(source, "Ticket")

    for _ in range(2):
        result = run_script(
            "backup_db.py", "--source", str(source), "--output-dir", str(backup_dir)
        )
        assert result.returncode == 0, result.stderr

    assert len(list(backup_dir.glob("opsdesk-*.db"))) == 2


def test_restore_refuses_to_overwrite_existing_destination(tmp_path: Path) -> None:
    backup = tmp_path / "backup.db"
    destination = tmp_path / "existing.db"
    make_database(backup, "Backup record")
    make_database(destination, "Keep this record")

    result = run_script("restore_db.py", str(backup), str(destination))

    assert result.returncode == 2
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("SELECT title FROM tickets").fetchone()[0] == "Keep this record"
    assert not Path(str(destination) + ".restore-tmp").exists()


def test_replace_restore_preserves_previous_destination(tmp_path: Path) -> None:
    backup = tmp_path / "backup.db"
    destination = tmp_path / "existing.db"
    make_database(backup, "Restored record")
    make_database(destination, "Previous record")

    result = run_script("restore_db.py", str(backup), str(destination), "--replace")

    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("SELECT title FROM tickets").fetchone()[0] == "Restored record"
    with closing(sqlite3.connect(str(destination) + ".pre-restore.bak")) as db:
        assert db.execute("SELECT title FROM tickets").fetchone()[0] == "Previous record"


def test_demo_seed_loads_example_records_only_into_an_empty_database(tmp_path: Path) -> None:
    database = tmp_path / "demo.db"
    environment = os.environ.copy()
    environment["OPSDESK_DB_PATH"] = str(database)

    result = run_script("seed_demo.py", env=environment)

    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM monitored_services").fetchone()[0] == 3

    second_run = run_script("seed_demo.py", env=environment)
    assert second_run.returncode == 1
    assert "database is not empty" in second_run.stderr


def test_demo_seed_refuses_to_touch_existing_records(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    make_database(database, "Keep this ticket")
    environment = os.environ.copy()
    environment["OPSDESK_DB_PATH"] = str(database)

    result = run_script("seed_demo.py", env=environment)

    assert result.returncode == 1
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT title FROM tickets").fetchone()[0] == "Keep this ticket"
        assert db.execute("SELECT COUNT(*) FROM monitored_services").fetchone()[0] == 0
