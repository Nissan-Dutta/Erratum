"""Nebius Token Factory (OpenAI-compatible) client with an app-level spending cap.

Env:
  NEBIUS_API_KEY        required for live calls
  NEBIUS_BASE_URL       default https://api.tokenfactory.nebius.com/v1
  MODEL_LIGHTNING / MODEL_SUPER / MODEL_ULTRA   model ids (auto-discovered if unset)
  DAILY_TOKEN_CAP       default 1_500_000 tokens/day across all users
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx

BASE = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
CAP = int(os.getenv("DAILY_TOKEN_CAP", "1500000"))

_lock = threading.Lock()
_usage = {"day": time.strftime("%Y-%m-%d"), "tokens": 0}
_models: dict[str, str] = {}


class BudgetExceeded(RuntimeError):
    pass


def key() -> str | None:
    return os.getenv("NEBIUS_API_KEY")


def usage() -> dict:
    return {**_usage, "cap": CAP}


def _charge(n: int):
    with _lock:
        today = time.strftime("%Y-%m-%d")
        if _usage["day"] != today:
            _usage.update(day=today, tokens=0)
        _usage["tokens"] += n


def _check_budget():
    if _usage["day"] == time.strftime("%Y-%m-%d") and _usage["tokens"] >= CAP:
        raise BudgetExceeded("Daily model budget reached. Cached demo papers still work.")


ROLES = ("lightning", "super", "ultra")
MODELS_RETRY_S = 60  # a failed or partial /models lookup is retried after this long
_models_checked_at = 0.0


def _model_ids() -> list[str]:
    try:
        r = httpx.get(f"{BASE}/models", headers={"Authorization": f"Bearer {key()}"}, timeout=20)
        return [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return []


def _pick_roles(ids: list[str]) -> dict[str, str | None]:
    nemo = [i for i in ids if "nemotron" in i.lower() and not i.lower().endswith("-vl")]  # text roles only

    def pick(*words):
        for w in words:
            for i in nemo:
                if w in i.lower():
                    return i
        return nemo[0] if nemo else None

    return {"lightning": pick("lightning", "nano", "mini"), "super": pick("super", "49b", "70b"),
            "ultra": pick("ultra", "253b", "super")}


def models() -> dict[str, str | None]:
    """Role -> model id. Env wins; otherwise pick Nemotron models from /models.
    Only a complete answer is cached, so one failed lookup can't disable the models until a restart."""
    global _models_checked_at
    if _models:
        return _models
    env = {r: os.getenv(f"MODEL_{r.upper()}") for r in ROLES}
    resolved: dict[str, str | None] = dict(env)
    if not all(env.values()) and key() and time.time() - _models_checked_at >= MODELS_RETRY_S:
        _models_checked_at = time.time()
        found = _pick_roles(_model_ids())
        resolved = {r: env[r] or found[r] for r in ROLES}
    if all(resolved.values()):
        _models.update(resolved)
    return resolved


last = threading.local()  # last.finish = finish_reason of this thread's latest call


def chat(role: str, system: str, user: str, max_tokens: int = 2000, json_mode: bool = False,
         think: bool = True) -> tuple[str, int]:
    """Nemotron 3 models reason before answering; reasoning arrives in a separate field but counts toward
    max_tokens. think=False turns it off (used for pure extraction, where code makes every decision)."""
    if not key():
        raise RuntimeError("NEBIUS_API_KEY not set")
    _check_budget()
    model = models().get(role)
    if not model:
        raise RuntimeError(f"No model available for role {role}")
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if not think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{BASE}/chat/completions", json=body, timeout=180,
                   headers={"Authorization": f"Bearer {key()}"})
    if r.status_code == 400 and json_mode:  # model may not support response_format
        body.pop("response_format")
        r = httpx.post(f"{BASE}/chat/completions", json=body, timeout=180, headers={"Authorization": f"Bearer {key()}"})
    r.raise_for_status()
    d = r.json()
    used = d.get("usage", {}).get("total_tokens", 0)
    _charge(used)
    choice = d["choices"][0]
    last.finish = choice.get("finish_reason")
    if last.finish == "length" and think:
        # Out of tokens mid-reasoning: content may hold leaked reasoning, not an answer.
        print(f"warning: {role} hit max_tokens={max_tokens}")
    return (choice["message"].get("content") or ""), used


def parse_json(s: str):
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            return json.loads(m.group(0))
        raise
