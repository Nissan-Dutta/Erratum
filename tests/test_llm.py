"""Model discovery must recover from a failed /models call (no network: httpx.get is faked)."""
from types import SimpleNamespace

import httpx
import pytest

from erratum import llm

NEMO_IDS = ["nvidia/Nemotron-3_5-Lightning", "nvidia/nemotron-3-super-120b-a12b", "nvidia/Nemotron-3-Ultra-550b-a55b"]


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test")
    for r in llm.ROLES:
        monkeypatch.delenv(f"MODEL_{r.upper()}", raising=False)
    monkeypatch.setattr(llm, "_models", {})
    monkeypatch.setattr(llm, "_models_checked_at", 0.0)


def _fake_http(monkeypatch, responses):
    calls = {"n": 0}

    def get(*a, **k):
        calls["n"] += 1
        item = responses[min(calls["n"], len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(json=lambda: {"data": [{"id": i} for i in item]})

    monkeypatch.setattr(httpx, "get", get)
    return calls


def test_failed_lookup_is_retried_and_recovers(fresh, monkeypatch):
    monkeypatch.setattr(llm, "MODELS_RETRY_S", 0)
    calls = _fake_http(monkeypatch, [httpx.ConnectError("boom"), NEMO_IDS])
    assert llm.models()["lightning"] is None
    assert llm.models()["ultra"] == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert calls["n"] == 2


def test_retries_are_rate_limited_by_backoff(fresh, monkeypatch):
    monkeypatch.setattr(llm, "MODELS_RETRY_S", 3600)
    calls = _fake_http(monkeypatch, [httpx.ConnectError("boom")])
    for _ in range(3):
        llm.models()
    assert calls["n"] == 1


def test_complete_answer_is_cached(fresh, monkeypatch):
    calls = _fake_http(monkeypatch, [NEMO_IDS])
    first = llm.models()
    assert first["super"] == "nvidia/nemotron-3-super-120b-a12b"
    assert llm.models() == first
    assert calls["n"] == 1


def test_env_overrides_skip_the_lookup(fresh, monkeypatch):
    for r, m in (("lightning", "a"), ("super", "b"), ("ultra", "c")):
        monkeypatch.setenv(f"MODEL_{r.upper()}", m)
    calls = _fake_http(monkeypatch, [NEMO_IDS])
    assert llm.models() == {"lightning": "a", "super": "b", "ultra": "c"}
    assert calls["n"] == 0
