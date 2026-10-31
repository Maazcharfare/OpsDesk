# OpsDesk release notes

## Project changes

- Separated dashboard markup, styles, and browser behavior into `templates/` and `static/` for maintainability.
- Replaced inline scripts/styles with same-origin assets and a restrictive Content Security Policy.
- Production mode now rejects missing, example, and passwords shorter than 32 UTF-8 bytes; Basic Auth comparison handles UTF-8 credentials safely.
- Split production and development dependencies so the container does not install test/lint packages.
- Added Ruff linting, CI coverage on Python 3.12 and 3.13, backup/restore integration tests, contribution and security guides, and an MIT license.
- Fixed Windows restore failures by closing SQLite connections before replacing database files.
- Added microseconds to backup names to avoid same-second filename collisions.
- Added a safe demo seed command with four tickets and three services; it refuses to modify non-empty databases and makes no network requests.

## Local verification

Verified in the local Windows workspace:

- Python syntax compilation passed.
- Ruff: all checks passed.
- Dependency audit: no known vulnerabilities found.
- Pytest: 48 tests passed.
- SQLite backup/restore round-trip passed; restored database returned `integrity_check: ok`.
- Local browser dashboard rendered all four demo tickets, status totals, and three services.
- Local health endpoint returned `{"status":"ok","application":"OpsDesk"}`.

The Docker image, Compose stack, Nginx TLS configuration, and public-host network controls require validation on a Linux host with Docker and real certificates. They were not represented as locally verified. The app is not published, and no Git remote is configured.
