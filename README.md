# OpsDesk

**A small IT support workspace for keeping track of requests and checking public endpoints.**

OpsDesk is aimed at an internal IT team that needs a simple place to record issues such as VPN access or laptop setup, see what is still open, and manually check whether a public website or API responds. The app runs locally and stores its data in SQLite.

Service checks are manual; OpsDesk does not run a background monitor or send alerts. The optional Docker setup is a deployment starter, not a hosted production service.

## What it does

- Create, search, filter, and update support tickets, including priority and status.
- Track ticket totals by status on the dashboard.
- Register public HTTP/HTTPS endpoints and manually check status, latency, and last result.
- Persist records in SQLite without deleting existing data during startup.
- Protect production routes with fail-closed Basic Auth and strict browser security headers.
- Write privacy-conscious audit logs that omit credentials, request bodies, query strings, and ticket text.
- Back up SQLite databases with the online backup API and integrity checks; restore safely without silent replacement.
- Run as a non-root container behind an HTTPS Nginx reverse proxy with rate limits.

## What this project demonstrates

- A browser dashboard backed by a FastAPI API and a persistent SQLite database.
- Ticket creation, search, filtering, status changes, and summary counts.
- Manual HTTP/HTTPS checks for registered public endpoints.
- Production safeguards, including fail-closed authentication, browser security headers, URL validation, and service checks disabled by default in production.
- Backup and restore commands that verify database integrity and protect an existing destination from accidental overwrite.

The security controls are part of the code, but they are not a substitute for an independent security review or a deployment-specific review.

## Technology

- Python 3.12+
- FastAPI, Uvicorn, HTTPX2
- SQLite
- HTML, CSS, and browser JavaScript
- Pytest and Ruff
- Docker Compose and Nginx for the optional deployment starter

## Run locally

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m uvicorn main:app --reload
```

### macOS or Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m uvicorn main:app --reload
```

Open <http://127.0.0.1:8000>. The local development server is for local use; do not expose it directly to the public internet. Stop it with `Ctrl+C`.

For a portfolio walkthrough, optionally load the sample dataset **before** creating real records:

```bash
python scripts/seed_demo.py
```

It adds four sample tickets and three public service entries without running any checks or making outbound requests. The script refuses to run against a non-empty database. Use a fresh `OPSDESK_DB_PATH` for a disposable demo.

## Verify changes

```bash
ruff check .
pip-audit -r requirements-dev.txt
python -m py_compile main.py test_main.py test_database_tools.py scripts/backup_db.py scripts/restore_db.py scripts/seed_demo.py
python -m pytest -v
```

GitHub Actions runs the same lint, syntax, and test checks on pushes and pull requests.

## API overview

Interactive documentation is available at `/docs` while running locally.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/api/tickets` | List tickets; supports `search`, `status`, and `priority` filters |
| `GET` | `/api/tickets/stats` | Ticket totals by status |
| `POST` | `/api/tickets` | Create a ticket |
| `PATCH` | `/api/tickets/{ticket_id}` | Update ticket details or status |
| `GET` | `/api/services` | List monitored services |
| `POST` | `/api/services` | Register a public service URL |
| `POST` | `/api/services/{service_id}/check` | Run a manual service check |

## Data and recovery

By default, the database is `opsdesk.db` beside `main.py`. Set `OPSDESK_DB_PATH` to use another path; the container uses `/data/opsdesk.db`. Startup uses `CREATE TABLE IF NOT EXISTS` and never drops existing tables.

Create and verify a backup:

```bash
python scripts/backup_db.py --source opsdesk.db --output-dir backups
```

Restore to a new path first:

```bash
python scripts/restore_db.py backups/opsdesk-YYYYMMDDTHHMMSS.ffffffZ.db restored-opsdesk.db
```

An existing destination is protected unless `--replace` is explicitly supplied. Replace mode preserves the prior destination as `.pre-restore.bak`. Stop the application before restoring a live database. Keep an encrypted off-host copy and periodically rehearse recovery; SQLite integrity checks alone do not prove application-level correctness.

## Security notes

- **Production authentication:** Set `OPSDESK_ENV=production`, a non-placeholder username, and a unique password with at least 32 UTF-8 bytes. Missing, example, or short credentials cause all routes to fail closed with `503`. Store real credentials in host secrets, never in Git. Basic Auth requires correctly configured HTTPS.
- **Browser protections:** The app and proxy use a restrictive Content Security Policy with same-origin scripts and styles, plus framing, MIME-sniffing, referrer, and permissions protections.
- **HTTPS and rate limits:** `deploy/nginx/default.conf` redirects HTTP to HTTPS, permits TLS 1.2/1.3, and applies request and connection limits. Replace `opsdesk.example.com` and provide trusted files at `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem` before starting the public stack. It intentionally will not silently downgrade when certificates are missing.
- **Service-check SSRF risk:** URL validation rejects many private, loopback, link-local, and metadata destinations; redirects and environment proxies are disabled. DNS can still change between validation and connection. Production checks are disabled by default. Do not enable them until host-level outbound firewall rules or a reviewed DNS-pinning design have been implemented and independently tested. Docker alone is not an egress firewall.
- **Container:** The image uses a non-root account. Compose applies a read-only root filesystem, drops Linux capabilities, and stores data in a named volume.
- **Audit and backups:** Configure host log rotation, retention, access controls, alerting, and encrypted off-host backups for a real deployment.

No software can be guaranteed “100% secure.” Tests and configuration checks do not replace an independent security review, vulnerability scan, deployment review, or restore drill.

## Optional Docker deployment

This is a deployment starter; it does not provision a domain, certificates, firewall rules, secret storage, or off-host backups.

1. On a supported Linux host, install Docker Engine and Compose and point a domain to the host.
2. Copy `.env.example` to `.env`. Replace both placeholders; generate a unique password of at least 32 random UTF-8 bytes. Never commit `.env`.
3. Install a trusted TLS certificate and key in `deploy/certs/`; update the Nginx `server_name`.
4. Validate and build with `docker compose config` and `docker compose build`.
5. Start with `docker compose up -d` only after the secret and certificate checks are complete.
6. Verify HTTPS, authentication, rate limits, logs, restarts, and a restore drill on the target host.
7. Leave production service checks disabled until outbound network controls have been verified.

The Docker image and Compose/Nginx stack need validation on a host with Docker and real TLS files. Local API tests do not certify the public deployment.

## Local Docker and HTTPS walkthrough (Windows)

The production Compose stack above expects a real domain and trusted certificate. For a local browser walkthrough, use the separate loopback-only stack and a self-signed certificate:

```powershell
.\scripts\new_local_tls.ps1 -TrustCertificate
docker compose -f compose.local.yaml config
docker compose -f compose.local.yaml up --build -d
docker compose -f compose.local.yaml exec app python scripts/seed_demo.py
```

Open <https://127.0.0.1:8443>. The generated certificate is limited to `localhost` and `127.0.0.1`; the script adds it to the current Windows user's trusted root store only when `-TrustCertificate` is supplied. The private key and certificate files stay under the Git-ignored `deploy/certs/` directory. Stop the local stack with `docker compose -f compose.local.yaml down`.

After the walkthrough, remove the local certificate from the current user's Windows certificate stores if you no longer need it to be trusted. Run this in PowerShell from the project directory; it leaves the Git-ignored certificate files available for a later local run:

```powershell
$thumbprint = (Get-PfxCertificate .\deploy\certs\localhost.cer).Thumbprint
Get-ChildItem Cert:\CurrentUser\Root, Cert:\CurrentUser\My |
    Where-Object Thumbprint -eq $thumbprint |
    Remove-Item
```

Never commit or share `deploy/certs/privkey.pem`; regenerate it locally with `scripts/new_local_tls.ps1` if it is removed or exposed.

This local stack binds only to loopback and uses a separate named database volume. Service checks can be started manually from the dashboard; the demo seed command never contacts those endpoints. Use the production `compose.yaml` only with a trusted domain certificate and host-level network controls.

## Repository layout

```text
main.py                 FastAPI API, authentication, database, and health checks
templates/index.html    Dashboard markup
static/app.css          Responsive dashboard styles
static/app.js           Dashboard interactions
scripts/                SQLite backup/restore and optional demo-data loader
test_main.py            API, validation, and security tests
test_database_tools.py  Backup and restore integration tests
deploy/nginx/           HTTPS reverse-proxy configuration
compose.local.yaml     Loopback-only local Docker and HTTPS walkthrough
scripts/new_local_tls.ps1 Generate a localhost-only certificate for Windows
.github/workflows/      CI checks
```

## License

OpsDesk is released under the MIT License. See [LICENSE](LICENSE).
