
import socket

import pytest
from fastapi.testclient import TestClient

import main
from main import app


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Use a temporary database so real OpsDesk data stays untouched."""
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test_opsdesk.db")


@pytest.fixture
def client():
    """Start the application and initialize its isolated test database."""
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------
# Health and dashboard
# --------------------------------------------------

def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": "OpsDesk",
    }


def test_homepage_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "OpsDesk" in response.text
    assert "Service Monitoring" in response.text
    assert "Support Tickets" in response.text
    assert "/static/app.js" in response.text
    assert '/static/app.css' in response.text
    assert '/static/app.js' in response.text


def test_static_dashboard_assets_load(client):
    css = client.get("/static/app.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert "summary-grid" in css.text
    assert javascript.status_code == 200
    assert 'ticketEditForm' in javascript.text


def test_api_documentation_is_available(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert '/static/api_docs.js' in response.text
    assert '/static/api_docs.css' in response.text
    assert 'cdn.jsdelivr.net' not in response.text

    script = client.get("/static/api_docs.js")
    assert script.status_code == 200
    assert 'fetch("/openapi.json"' in script.text


# --------------------------------------------------
# Ticket creation and validation
# --------------------------------------------------

def test_create_ticket(client):
    response = client.post(
        "/api/tickets",
        json={
            "title": "Laptop Wi-Fi Issue",
            "description": "Cannot connect to office Wi-Fi",
            "priority": "High",
        },
    )

    assert response.status_code == 201

    ticket = response.json()
    assert ticket["title"] == "Laptop Wi-Fi Issue"
    assert ticket["description"] == "Cannot connect to office Wi-Fi"
    assert ticket["priority"] == "High"
    assert ticket["status"] == "Open"
    assert ticket["id"] > 0


def test_create_ticket_with_default_values(client):
    response = client.post(
        "/api/tickets",
        json={"title": "Keyboard Issue"},
    )

    assert response.status_code == 201
    assert response.json()["priority"] == "Medium"
    assert response.json()["status"] == "Open"
    assert response.json()["description"] == ""


def test_list_tickets(client):
    client.post(
        "/api/tickets",
        json={"title": "First Ticket", "priority": "Low"},
    )
    client.post(
        "/api/tickets",
        json={"title": "Second Ticket", "priority": "High"},
    )

    response = client.get("/api/tickets")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["title"] == "Second Ticket"


def test_invalid_ticket_priority_is_rejected(client):
    response = client.post(
        "/api/tickets",
        json={
            "title": "Test ticket",
            "description": "Validation test",
            "priority": "Urgent",
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("title", ["", "AB", "  "])
def test_invalid_ticket_titles_are_rejected(client, title):
    response = client.post(
        "/api/tickets",
        json={"title": title, "priority": "Medium"},
    )

    assert response.status_code == 422


def test_ticket_title_is_trimmed(client):
    response = client.post(
        "/api/tickets",
        json={"title": "  Network Issue  ", "priority": "Medium"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Network Issue"


def test_update_ticket_status(client):
    created = client.post(
        "/api/tickets",
        json={"title": "Keyboard Issue", "priority": "Medium"},
    )
    ticket_id = created.json()["id"]

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"status": "Resolved"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Resolved"


def test_invalid_ticket_status_is_rejected(client):
    created = client.post(
        "/api/tickets",
        json={"title": "Printer Issue", "priority": "Low"},
    )

    response = client.patch(
        f"/api/tickets/{created.json()['id']}",
        json={"status": "Cancelled"},
    )

    assert response.status_code == 422


def test_update_missing_ticket_returns_404(client):
    response = client.patch(
        "/api/tickets/99999",
        json={"status": "Resolved"},
    )

    assert response.status_code == 404


# --------------------------------------------------
# Service URL validation
# --------------------------------------------------

def test_localhost_service_url_is_rejected(client):
    response = client.post(
        "/api/services",
        json={
            "name": "Local Test Service",
            "url": "http://localhost:8000",
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "http://127.0.0.1",
        "http://192.168.1.1",
        "http://10.0.0.1",
        "http://user:password@example.com",
        "http://example.com:invalid",
    ],
)
def test_unsafe_or_invalid_service_urls_are_rejected(client, url):
    response = client.post(
        "/api/services",
        json={"name": "Test Service", "url": url},
    )

    assert response.status_code == 422


def test_unresolvable_hostname_is_rejected(client, monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("Test hostname not found")

    monkeypatch.setattr(main.socket, "getaddrinfo", fake_getaddrinfo)

    response = client.post(
        "/api/services",
        json={
            "name": "Test Service",
            "url": "https://nonexistent.example",
        },
    )

    assert response.status_code == 422


# --------------------------------------------------
# Service management
# --------------------------------------------------

def test_create_service(client):
    response = client.post(
        "/api/services",
        json={
            "name": "Example Website",
            "url": "https://8.8.8.8",
        },
    )

    assert response.status_code == 201

    service = response.json()
    assert service["name"] == "Example Website"
    assert service["url"] == "https://8.8.8.8"
    assert service["status"] == "UNKNOWN"
    assert service["id"] > 0


def test_list_services(client):
    client.post(
        "/api/services",
        json={
            "name": "Example Website",
            "url": "https://8.8.8.8",
        },
    )

    response = client.get("/api/services")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Example Website"


def test_duplicate_service_url_is_rejected(client):
    payload = {
        "name": "Example Website",
        "url": "https://8.8.8.8",
    }

    first = client.post("/api/services", json=payload)
    second = client.post(
        "/api/services",
        json={**payload, "name": "Another Name"},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_missing_service_check_returns_404(client):
    response = client.post("/api/services/99999/check")

    assert response.status_code == 404


def test_service_check_records_success(client, monkeypatch):
    created = client.post(
        "/api/services",
        json={
            "name": "Example Website",
            "url": "https://8.8.8.8",
        },
    )
    service_id = created.json()["id"]

    class FakeResponse:
        status_code = 200

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url == "https://8.8.8.8"
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "Client", FakeHTTPClient)

    response = client.post(f"/api/services/{service_id}/check")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.json()["http_status_code"] == 200
    assert response.json()["response_time_ms"] >= 0
    assert response.json()["last_checked_at"] is not None
    assert response.json()["error_message"] is None


def test_service_check_records_network_failure(client, monkeypatch):
    created = client.post(
        "/api/services",
        json={
            "name": "Example Website",
            "url": "https://8.8.8.8",
        },
    )
    service_id = created.json()["id"]

    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            raise main.httpx.ConnectError("Simulated connection failure")

    monkeypatch.setattr(main.httpx, "Client", FakeHTTPClient)

    response = client.post(f"/api/services/{service_id}/check")

    assert response.status_code == 200
    assert response.json()["status"] == "DOWN"
    assert response.json()["error_message"] is not None
    assert response.json()["last_checked_at"] is not None


# --------------------------------------------------
# Database isolation
# --------------------------------------------------

def test_tests_use_a_separate_database(client):
    client.post(
        "/api/tickets",
        json={"title": "Temporary Test Ticket"},
    )

    assert main.DB_PATH.name == "test_opsdesk.db"
    assert main.DB_PATH.exists()

    with main.get_connection() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM tickets"
        ).fetchone()[0]

    assert count == 1

# --------------------------------------------------
# Ticket search, filters, edits, and dashboard statistics
# --------------------------------------------------

def test_ticket_search_and_filters(client):
    first = client.post("/api/tickets", json={
        "title": "Wi-Fi connection issue", "description": "Laptop cannot connect", "priority": "High"
    })
    second = client.post("/api/tickets", json={
        "title": "Printer offline", "description": "Office printer", "priority": "Low"
    })
    assert first.status_code == 201
    assert second.status_code == 201
    client.patch(f"/api/tickets/{first.json()['id']}", json={"status": "In Progress"})

    assert len(client.get("/api/tickets", params={"search": "wi-fi"}).json()) == 1
    assert len(client.get("/api/tickets", params={"status": "In Progress"}).json()) == 1
    assert len(client.get("/api/tickets", params={"priority": "Low"}).json()) == 1
    assert len(client.get("/api/tickets", params={"search": "office", "priority": "Low"}).json()) == 1


def test_ticket_stats_counts_all_statuses(client):
    client.post("/api/tickets", json={"title": "Open ticket"})
    in_progress = client.post("/api/tickets", json={"title": "Progress ticket"}).json()
    resolved = client.post("/api/tickets", json={"title": "Resolved ticket"}).json()
    client.patch(f"/api/tickets/{in_progress['id']}", json={"status": "In Progress"})
    client.patch(f"/api/tickets/{resolved['id']}", json={"status": "Resolved"})

    assert client.get("/api/tickets/stats").json() == {
        "total": 3, "open": 1, "in_progress": 1, "resolved": 1
    }


def test_ticket_details_and_priority_can_be_updated(client):
    created = client.post("/api/tickets", json={"title": "Old ticket", "description": "Old", "priority": "Low"})
    ticket_id = created.json()["id"]
    response = client.patch(f"/api/tickets/{ticket_id}", json={
        "title": "Updated ticket", "description": "Updated description", "priority": "Critical"
    })
    assert response.status_code == 200
    assert response.json()["title"] == "Updated ticket"
    assert response.json()["description"] == "Updated description"
    assert response.json()["priority"] == "Critical"


def test_ticket_update_requires_at_least_one_field(client):
    created = client.post("/api/tickets", json={"title": "Existing ticket"}).json()
    response = client.patch(f"/api/tickets/{created['id']}", json={})
    assert response.status_code == 422


def test_invalid_ticket_filters_are_rejected(client):
    assert client.get("/api/tickets", params={"status": "Closed"}).status_code == 422
    assert client.get("/api/tickets", params={"priority": "Urgent"}).status_code == 422


def test_security_headers_are_present(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_production_mode_fails_closed_without_credentials(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "AUTH_USERNAME", "")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "")
    response = client.get("/")
    assert response.status_code == 503


def test_production_mode_rejects_example_credentials(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "AUTH_USERNAME", "replace-with-a-unique-admin-name")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "replace-with-a-long-random-secret-at-least-32-characters")

    assert client.get("/health").status_code == 503


def test_production_mode_rejects_short_password(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "AUTH_USERNAME", "opsadmin")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "too-short")

    assert client.get("/health").status_code == 503


def test_production_mode_requires_basic_auth(client, monkeypatch):
    import base64
    import main
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "AUTH_USERNAME", "opsadmin")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "a-test-only-password-longer-than-32-chars")
    assert client.get("/").status_code == 401
    token = base64.b64encode("opsadmin:pässword-with-more-than-32-chars".encode("utf-8")).decode("ascii")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "pässword-with-more-than-32-chars")
    response = client.get("/health", headers={"Authorization": f"bAsIc {token}"})
    assert response.status_code == 200
    assert response.headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"


def test_production_service_checks_disabled_by_default(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "APP_ENV", "production")
    monkeypatch.setattr(main, "ALLOW_SERVICE_CHECKS", False)
    monkeypatch.setattr(main, "AUTH_USERNAME", "opsadmin")
    monkeypatch.setattr(main, "AUTH_PASSWORD", "a-test-only-password-longer-than-32-chars")
    token = __import__("base64").b64encode(
        b"opsadmin:a-test-only-password-longer-than-32-chars"
    ).decode("ascii")
    response = client.post("/api/services/1/check", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 503
    assert "disabled in production" in response.json()["detail"]


def test_mutation_and_error_requests_emit_audit_log(client, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="opsdesk.audit"):
        response = client.post("/api/tickets", json={"title": "Audit test"})
    assert response.status_code == 201
    assert "method=POST path=/api/tickets status=201" in caplog.text
    assert "Audit test" not in caplog.text
