"""Erratum web app. Run: uvicorn app:app --port 7860"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from erratum import llm, pipeline

ROOT = Path(__file__).parent
DEMO_CACHE = ROOT / "demos" / "cache"          # precomputed live reports, shipped with the code
CACHE = Path(os.getenv("CACHE_DIR", "/tmp/erratum-cache"))
CACHE.mkdir(parents=True, exist_ok=True)
DEMOS = json.loads((ROOT / "demos" / "demos.json").read_text())
RATE = int(os.getenv("AUDITS_PER_HOUR", "8"))
MAX_CHARS = 200_000

app = FastAPI(title="Erratum")
_hits: dict[str, deque] = defaultdict(deque)


class AuditIn(BaseModel):
    input: str | None = None   # PMCID or DOI
    text: str | None = None    # pasted text
    demo: str | None = None    # demo id


def _client_ip(request: Request) -> str:
    """Vercel overwrites X-Forwarded-For with the real client IP, so it's only trustworthy there.
    Anywhere else (Docker, plain uvicorn) a client can send any value, so use the socket peer."""
    if os.getenv("VERCEL"):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _limited(ip: str) -> bool:
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE:
        return True
    q.append(now)
    return False


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/demos")
def demos():
    return [{k: d[k] for k in ("id", "label", "blurb")} for d in DEMOS]


@app.get("/api/health")
def health():
    return {"live_models": bool(llm.key()), "tavily": bool(os.getenv("TAVILY_API_KEY")), "usage": llm.usage(),
            "models": llm.models() if llm.key() else {}}


@app.post("/api/audit")
def audit(body: AuditIn, request: Request):
    meta: dict = {}
    if body.demo:
        d = next((d for d in DEMOS if d["id"] == body.demo), None)
        if not d:
            raise HTTPException(404, "Unknown demo")
        for cached in (CACHE / f"demo-{d['id']}.json", DEMO_CACHE / f"{d['id']}.json"):
            if cached.exists():
                return JSONResponse(json.loads(cached.read_text()))
        if d.get("pmcid"):  # a real open-access paper, fetched from Europe PMC
            pp = pipeline.resolve(d["pmcid"])
            text, meta = pp["text"], {"title": pp["title"], "pmcid": pp["pmcid"], "doi": pp["doi"], "note": d.get("note")}
        else:
            text, meta = (ROOT / "demos" / d["file"]).read_text(), {"title": d["label"], "note": d.get("note")}
    else:
        if _limited(_client_ip(request)):
            raise HTTPException(429, f"Limit is {RATE} audits per hour. Try a demo paper.")
        if body.text and body.text.strip():
            text, meta = body.text, {"title": "Pasted text"}
        elif body.input:
            try:
                p = pipeline.resolve(body.input)
            except ValueError as e:
                raise HTTPException(400, str(e))
            text, meta = p["text"], {"title": p["title"], "pmcid": p["pmcid"], "doi": p["doi"]}
        else:
            raise HTTPException(400, "Nothing to audit.")
    text = text[:MAX_CHARS]
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    cf = CACHE / f"{h}.json"
    if cf.exists() and not body.demo:
        return JSONResponse(json.loads(cf.read_text()))
    t0 = time.time()
    try:
        rep = pipeline.audit(text, meta)
    except llm.BudgetExceeded as e:
        raise HTTPException(503, str(e))
    rep["seconds"] = round(time.time() - t0, 1)
    rep["chars"] = len(text)
    for f in rep["findings"]:
        f.pop("span", None)
    if llm.key():
        cf.write_text(json.dumps(rep))
        if body.demo:
            (CACHE / f"demo-{body.demo}.json").write_text(json.dumps(rep))
    return JSONResponse(rep)
