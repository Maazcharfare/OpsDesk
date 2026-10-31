#!/usr/bin/env python3
"""Load a small, clearly labeled portfolio demo dataset into an empty OpsDesk database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import get_connection, initialize_database  # noqa: E402


TICKETS = [
    (
        "VPN access for a new starter",
        "Confirm the user group assignment and verify access from the managed laptop.",
        "High",
        "Open",
    ),
    (
        "Payroll dashboard loads slowly",
        "Review the browser trace and check the latest application release notes.",
        "Medium",
        "In Progress",
    ),
    (
        "Meeting room display cable replacement",
        "Replace the damaged HDMI cable and confirm the room display works.",
        "Low",
        "Resolved",
    ),
    (
        "Laptop enrollment certificate prompt",
        "Enrollment is blocked by a certificate prompt during device setup.",
        "Critical",
        "Open",
    ),
]

SERVICES = [
    ("GitHub API", "https://api.github.com"),
    ("Python Package Index", "https://pypi.org"),
    ("Example Domain", "https://example.com"),
]


def main() -> int:
    initialize_database()
    with get_connection() as db:
        ticket_count = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        service_count = db.execute("SELECT COUNT(*) FROM monitored_services").fetchone()[0]
        if ticket_count or service_count:
            raise SystemExit(
                "Demo data was not loaded: the database is not empty. "
                "Choose a new OPSDESK_DB_PATH to protect existing records."
            )
        db.executemany(
            "INSERT INTO tickets (title, description, priority, status) VALUES (?, ?, ?, ?)",
            TICKETS,
        )
        db.executemany(
            "INSERT INTO monitored_services (name, url) VALUES (?, ?)",
            SERVICES,
        )
    print(f"Loaded {len(TICKETS)} demo tickets and {len(SERVICES)} demo services.")
    print("Service checks remain manual; no external requests were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
