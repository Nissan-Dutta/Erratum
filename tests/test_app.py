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
