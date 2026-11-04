"""HTTP-level tests for the FastAPI app (offline: no model or Europe PMC calls)."""
import pytest
from fastapi.testclient import TestClient

import app as A


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "RATE", 2)
    A._hits.clear()
    return TestClient(A.app)


def _audit_codes(client, forwarded_for: list[str]) -> list[int]:
    return [client.post("/api/audit", json={"text": "x"}, headers={"x-forwarded-for": ip}).status_code
            for ip in forwarded_for]


def test_forwarded_for_is_ignored_outside_vercel(client, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert _audit_codes(client, ["10.0.0.1", "10.0.0.2", "10.0.0.3"]) == [200, 200, 429]


def test_forwarded_for_is_trusted_on_vercel(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert _audit_codes(client, ["10.0.0.1", "10.0.0.1", "10.0.0.1", "10.0.0.2"]) == [200, 200, 429, 200]


def test_home_page_ignores_range_header(client):
    spec = ",".join(f"{2 * i}-{2 * i}" for i in range(4000))  # disjoint ranges: quadratic in FileResponse
    r = client.get("/", headers={"Range": "bytes=" + spec})
    assert r.status_code == 200
    assert r.content == A.INDEX_HTML
    assert "accept-ranges" not in r.headers


def test_security_headers_on_every_response(client):
    for r in (client.get("/"), client.get("/api/demos"), client.get("/api/health")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert r.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_invalid_demo_id_returns_404(client):
    # Path traversal patterns and unknown demos must be cleanly rejected
    for bad_demo in ("../demos/spatula", "../../etc/passwd", "unknown", "spatula/../synthetic"):
        r = client.post("/api/audit", json={"demo": bad_demo})
        assert r.status_code == 404
        assert r.json()["detail"] == "Unknown demo"


def test_valid_cached_demo_succeeds(client):
    r = client.post("/api/audit", json={"demo": "spatula"})
    assert r.status_code == 200
    assert "findings" in r.json()


def test_input_validation_length_limits(client):
    # Oversized payload rejected with 422 Unprocessable Entity
    r_text = client.post("/api/audit", json={"text": "a" * (A.MAX_CHARS + 1)})
    assert r_text.status_code == 422

    r_input = client.post("/api/audit", json={"input": "PMC" + "1" * 600})
    assert r_input.status_code == 422

    r_demo = client.post("/api/audit", json={"demo": "a" * 100})
    assert r_demo.status_code == 422
