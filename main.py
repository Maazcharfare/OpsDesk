
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import base64
import hmac
import ipaddress
import logging
import os
import socket
import sqlite3
import time
from urllib.parse import urlparse

import httpx2 as httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# --------------------------------------------------
# OpsDesk configuration
# --------------------------------------------------

DB_PATH = Path(os.getenv("OPSDESK_DB_PATH", str(Path(__file__).with_name("opsdesk.db")))).expanduser()

PRIORITIES = {"Low", "Medium", "High", "Critical"}
TICKET_STATUSES = {"Open", "In Progress", "Resolved"}

SERVICE_TIMEOUT_SECONDS = 5.0
SERVICE_CONNECT_TIMEOUT_SECONDS = 2.0
MAX_ERROR_LENGTH = 500


# --------------------------------------------------
# Database
# --------------------------------------------------

@contextmanager
def get_connection():
    """Open a database connection and commit or roll back safely."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database():
    """
    Create missing tables without deleting existing records.
    Never drop, reset, or recreate the existing database.
    """
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'Medium'
                    CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
                status TEXT NOT NULL DEFAULT 'Open'
                    CHECK (status IN ('Open', 'In Progress', 'Resolved')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS monitored_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'UNKNOWN',
                response_time_ms REAL,
                http_status_code INTEGER,
                last_checked_at TEXT,
                error_message TEXT
            )
        """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="OpsDesk",
    description="IT Operations and Service Monitoring Platform",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

PROJECT_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_DIR / "static"
TEMPLATE_FILE = PROJECT_DIR / "templates" / "index.html"
API_DOCS_FILE = PROJECT_DIR / "templates" / "api_docs.html"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Production access control is deliberately fail-closed. Configure these
# environment variables and terminate HTTPS at a trusted reverse proxy before
# exposing the application beyond localhost.
APP_ENV = os.getenv("OPSDESK_ENV", "development").strip().lower()
ALLOW_SERVICE_CHECKS = os.getenv("OPSDESK_ALLOW_SERVICE_CHECKS", "false").strip().lower() == "true"
AUDIT_LOGGER = logging.getLogger("opsdesk.audit")
if not logging.getLogger().handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
AUTH_USERNAME = os.getenv("OPSDESK_USERNAME", "")
AUTH_PASSWORD = os.getenv("OPSDESK_PASSWORD", "")


@app.middleware("http")
async def security_and_access_middleware(request, call_next):
    """Apply access control, baseline headers, and privacy-conscious request audit logs."""
    started = time.perf_counter()
    if APP_ENV == "production":
        if not production_auth_is_configured():
            response = JSONResponse(
                status_code=503,
                content={"detail": "Production authentication is not securely configured"},
            )
        else:
            authorization = request.headers.get("authorization", "")
            valid = False
            scheme, separator, encoded = authorization.partition(" ")
            if separator and scheme.casefold() == "basic":
                try:
                    decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                    username, separator, password = decoded.partition(":")
                    username_match = hmac.compare_digest(
                        username.encode("utf-8"), AUTH_USERNAME.strip().encode("utf-8")
                    )
                    password_match = hmac.compare_digest(
                        password.encode("utf-8"), AUTH_PASSWORD.encode("utf-8")
                    )
                    valid = bool(separator) and username_match and password_match
                except (ValueError, UnicodeDecodeError):
                    valid = False
            if not valid:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                    headers={"WWW-Authenticate": 'Basic realm="OpsDesk", charset="UTF-8"'},
                )
            else:
                response = await call_next(request)
    else:
        response = await call_next(request)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} or response.status_code >= 400:
        # Do not log request bodies, credentials, query strings, or user content.
        AUDIT_LOGGER.info("method=%s path=%s status=%s duration_ms=%.2f", request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    if APP_ENV == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


PLACEHOLDER_USERNAMES = {"replace-with-a-unique-admin-name", "change-me", "replace-me"}
PLACEHOLDER_PASSWORDS = {
    "replace-with-a-long-random-secret-at-least-32-characters",
    "change-me",
    "replace-me",
}


def production_auth_is_configured() -> bool:
    """Require an operator-supplied, non-placeholder secret before production access."""
    username = AUTH_USERNAME.strip()
    password = AUTH_PASSWORD
    return bool(
        username
        and username.casefold() not in PLACEHOLDER_USERNAMES
        and password
        and password.casefold() not in PLACEHOLDER_PASSWORDS
        and len(password.encode("utf-8")) >= 32
    )


# --------------------------------------------------
# Request validation
# --------------------------------------------------

class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    priority: str = "Medium"


class TicketUpdate(BaseModel):
    status: str | None = None
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    priority: str | None = None


class ServiceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    url: str = Field(min_length=8, max_length=2048)


# --------------------------------------------------
# Service URL validation
# --------------------------------------------------

def validate_service_url(url: str):
    """
    Allow only HTTP/HTTPS URLs whose hostname resolves to public IPs.
    Redirects are disabled during checks to reduce SSRF risk.
    """
    try:
        parsed = urlparse(url.strip())

        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(
                status_code=422,
                detail="Only HTTP and HTTPS URLs are allowed",
            )

        if not parsed.hostname:
            raise HTTPException(
                status_code=422,
                detail="Enter a valid public website URL",
            )

        if parsed.username or parsed.password:
            raise HTTPException(
                status_code=422,
                detail="URLs containing credentials are not allowed",
            )

        # Accessing .port also validates malformed port values.
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise HTTPException(
                status_code=422,
                detail="Invalid URL port",
            )

        host = parsed.hostname.lower().rstrip(".")

        if host == "localhost" or host.endswith(".localhost"):
            raise HTTPException(
                status_code=422,
                detail="Localhost URLs are not allowed",
            )

        # Reject IP literals that are not publicly routable.
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None

        if address is not None:
            if not address.is_global:
                raise HTTPException(
                    status_code=422,
                    detail="Only public IP addresses are allowed",
                )
            return

        # Resolve domain names and reject private/local destinations.
        try:
            results = socket.getaddrinfo(
                host,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (socket.gaierror, OSError):
            raise HTTPException(
                status_code=422,
                detail="Hostname could not be resolved",
            )

        if not results:
            raise HTTPException(
                status_code=422,
                detail="Hostname has no usable IP addresses",
            )

        for result in results:
            resolved_ip = result[4][0].split("%")[0]

            try:
                resolved_address = ipaddress.ip_address(resolved_ip)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid IP address returned by DNS",
                )

            if not resolved_address.is_global:
                raise HTTPException(
                    status_code=422,
                    detail="Hostname resolves to a non-public IP",
                )

    except HTTPException:
        raise
    except (ValueError, UnicodeError):
        raise HTTPException(
            status_code=422,
            detail="Invalid URL format",
        )


# --------------------------------------------------
# Health endpoint
# --------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "OpsDesk",
    }


# --------------------------------------------------
# Support ticket API
# --------------------------------------------------

@app.get("/api/tickets")
def list_tickets(
    search: str = Query(default="", max_length=120),
    status: str | None = None,
    priority: str | None = None,
):
    """List tickets with optional case-insensitive search and filters."""
    if status is not None and status not in TICKET_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status filter")
    if priority is not None and priority not in PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid priority filter")

    clauses = []
    params = []
    if search.strip():
        pattern = f"%{search.strip()}%"
        clauses.append("(title LIKE ? OR description LIKE ?)")
        params.extend([pattern, pattern])
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM tickets" + where + " ORDER BY id DESC", params
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/tickets/stats")
def ticket_stats():
    """Return dashboard ticket totals, including zero-count statuses."""
    with get_connection() as db:
        total = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        rows = db.execute(
            "SELECT status, COUNT(*) AS count FROM tickets GROUP BY status"
        ).fetchall()
    counts = {status: 0 for status in TICKET_STATUSES}
    counts.update({row["status"]: row["count"] for row in rows})
    return {"total": total, **{key.lower().replace(" ", "_"): value for key, value in counts.items()}}


@app.post("/api/tickets", status_code=201)
def create_ticket(ticket: TicketCreate):
    title = ticket.title.strip()
    description = ticket.description.strip()

    if len(title) < 3:
        raise HTTPException(
            status_code=422,
            detail="Title must have at least 3 characters",
        )

    if ticket.priority not in PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail="Invalid priority",
        )

    with get_connection() as db:
        cursor = db.execute(
            """
            INSERT INTO tickets (title, description, priority)
            VALUES (?, ?, ?)
            """,
            (title, description, ticket.priority),
        )

        row = db.execute(
            "SELECT * FROM tickets WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


@app.patch("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: int, update: TicketUpdate):
    changes = update.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    if "status" in changes and changes["status"] not in TICKET_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    if "priority" in changes and changes["priority"] not in PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid priority")
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if len(changes["title"]) < 3:
            raise HTTPException(status_code=422, detail="Title must have at least 3 characters")
    if "description" in changes:
        changes["description"] = changes["description"].strip()

    with get_connection() as db:
        existing = db.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Ticket not found")
        assignments = ", ".join(f"{field} = ?" for field in changes)
        db.execute(
            f"UPDATE tickets SET {assignments} WHERE id = ?",
            [*changes.values(), ticket_id],
        )
        row = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return dict(row)


# --------------------------------------------------
# Service monitoring API
# --------------------------------------------------

@app.get("/api/services")
def list_services():
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM monitored_services ORDER BY id DESC"
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/services", status_code=201)
def create_service(service: ServiceCreate):
    name = service.name.strip()
    url = service.url.strip()

    if len(name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Service name must have at least 2 characters",
        )

    validate_service_url(url)

    with get_connection() as db:
        try:
            cursor = db.execute(
                """
                INSERT INTO monitored_services (name, url)
                VALUES (?, ?)
                """,
                (name, url),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="This URL is already registered",
            )

        row = db.execute(
            "SELECT * FROM monitored_services WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


@app.post("/api/services/{service_id}/check")
def check_service(service_id: int):
    if APP_ENV == "production" and not ALLOW_SERVICE_CHECKS:
        raise HTTPException(503, "Service checks are disabled in production until outbound network restrictions are configured")

    with get_connection() as db:
        service = db.execute(
            "SELECT * FROM monitored_services WHERE id = ?",
            (service_id,),
        ).fetchone()

    if service is None:
        raise HTTPException(
            status_code=404,
            detail="Service not found",
        )

    validate_service_url(service["url"])

    started = time.perf_counter()
    status = "DOWN"
    http_status = None
    error_message = None

    try:
        # Do not follow redirects or use environment proxy settings.
        timeout = httpx.Timeout(
            SERVICE_TIMEOUT_SECONDS,
            connect=SERVICE_CONNECT_TIMEOUT_SECONDS,
            read=2.0,
            write=2.0,
            pool=2.0,
        )
        # Revalidate immediately before connecting; redirects and environment
        # proxies are disabled. Public DNS can still change between validation
        # and connection, so hostile deployments need network egress controls or
        # a DNS-pinning transport to eliminate DNS-rebinding risk.
        validate_service_url(service["url"])
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(service["url"])
            http_status = response.status_code
            # HTTP responses below 500 indicate the server responded.
            status = "UP" if http_status < 500 else "DOWN"
    except httpx.HTTPError as exc:
        error_message = str(exc)[:MAX_ERROR_LENGTH]

    elapsed = round(
        (time.perf_counter() - started) * 1000,
        2,
    )
    checked_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as db:
        db.execute(
            """
            UPDATE monitored_services
            SET status = ?,
                response_time_ms = ?,
                http_status_code = ?,
                last_checked_at = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                status,
                elapsed,
                http_status,
                checked_at,
                error_message,
                service_id,
            ),
        )

        row = db.execute(
            "SELECT * FROM monitored_services WHERE id = ?",
            (service_id,),
        ).fetchone()

    return dict(row)

# --------------------------------------------------
# OpsDesk web dashboard
# --------------------------------------------------

@app.get("/", response_class=FileResponse)
def home():
    return FileResponse(TEMPLATE_FILE, media_type="text/html")


@app.get("/docs", response_class=FileResponse, include_in_schema=False)
def api_docs():
    """Serve the self-hosted API reference without external scripts or styles."""
    return FileResponse(API_DOCS_FILE, media_type="text/html")
