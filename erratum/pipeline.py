"""Ingest -> extract (regex + Nemotron Lightning) -> code checks -> Super triage / Ultra review -> Tavily prereg."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import httpx

from . import checkers as C
from . import llm

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


# ---------------------------------------------------------------- ingest

def resolve(ident: str) -> dict:
    """PMCID, DOI or Europe PMC URL -> {title, pmcid, doi, text}."""
    ident = ident.strip()
    m = re.search(r"PMC\d+", ident, re.I)
    pmcid = m.group(0).upper() if m else None
    doi = None
    if not pmcid:
        d = re.search(r"10\.\d{4,9}/\S+", ident)
        if not d:
            raise ValueError("Give a PMCID (e.g. PMC1234567), a DOI, or paste the text.")
        doi = d.group(0).rstrip(".")
        r = httpx.get(f"{EPMC}/search", params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "lite"}, timeout=30)
        hits = r.json().get("resultList", {}).get("result", [])
        pmcid = next((h.get("pmcid") for h in hits if h.get("pmcid")), None)
        if not pmcid:
            raise ValueError("No open-access full text in Europe PMC for that DOI. Paste the text instead.")
    r = httpx.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=60)
    if r.status_code != 200 or not r.text.strip():
        raise ValueError(f"Europe PMC has no full text for {pmcid}.")
    root = ET.fromstring(r.content)
    title = " ".join("".join(t.itertext()) for t in root.iter("article-title"))[:300]
    parts = []
    for tag in ("abstract", "body"):
        for el in root.iter(tag):
            for p in el.iter("p"):
                parts.append(" ".join("".join(p.itertext()).split()))
    doi = doi or next((e.text for e in root.iter("article-id") if e.get("pub-id-type") == "doi"), None)
    return {"title": title or pmcid, "pmcid": pmcid, "doi": doi, "text": "\n\n".join(parts)}


# ---------------------------------------------------------------- Nemotron extraction

EXTRACT_SYS = """You extract numbers from a scientific paper for automated recomputation. You never judge correctness.
Return ONLY a JSON object with these keys (empty lists if none):
{
 "grim": [{"quote": str, "mean": str (exactly as printed, keep trailing zeros), "n": int|null (per-cell n for THIS mean), "scale_quote": str|null (verbatim text, from anywhere in the paper and often in Methods, describing how this measure was scored, e.g. \"a single 7-point Likert item\"), "items": int|null (number of items averaged, 1 for single-item), "integer_valued": bool (true if, per scale_quote, every response is a whole number: counts, Likert/rating items, integer scores)}],
 "percents": [{"quote": str, "x": int, "n": int, "pct": str (as printed)}],
 "arithmetic": [{"quote": str, "operands": [{"value": number, "unit": str|null}], "op": "multiply"|"divide"|"add"|"subtract", "claimed": {"value": number, "unit": str|null}}],
 "stats": [{"quote": str, "test": "t"|"F"|"r"|"chi2"|"z", "stat": str, "df1": str|null, "df2": str|null, "p_op": "="|"<"|">", "p": str}],
 "sample_size": int|null,
 "primary_outcome": str|null
}
Rules: quote must be copied verbatim from the text (max 200 chars). Only include an arithmetic item when the paper itself states a computed result from stated inputs (e.g. intake = mass x dose). Use null when a value is not stated; never guess n.
List EVERY reported mean (M) of a measured variable under "grim", whatever its scale (not test statistics or correlations); integer_valued is a separate field, not a filter."""


def _chunks(text: str, size: int = 24000):
    paras, cur = text.split("\n\n"), ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            yield cur
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        yield cur


def nemotron_extract(text: str) -> tuple[dict, int]:
    out = {"grim": [], "percents": [], "arithmetic": [], "stats": [], "sample_size": None, "primary_outcome": None}
    tokens = 0
    for ch in list(_chunks(text))[:4]:
        raw, used = llm.chat("lightning", EXTRACT_SYS, ch, max_tokens=4000, json_mode=True, think=False)
        tokens += used
        try:
            d = llm.parse_json(raw)
        except Exception:
            continue
        for k in ("grim", "percents", "arithmetic", "stats"):
            out[k] += [x for x in (d.get(k) or []) if isinstance(x, dict)]
        out["sample_size"] = out["sample_size"] or d.get("sample_size")
        out["primary_outcome"] = out["primary_outcome"] or d.get("primary_outcome")
    return out, tokens


def _verbatim(q: str, text: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return bool(q) and norm(q)[:60] in norm(text)


MEAN_RE = re.compile(r"\bM\s*=|\bmeans?\b|\baverage", re.I)
SINGLE_ITEM_RE = re.compile(r"\bsingle\b.{0,40}\b(likert|\d+-point|rating)|\b(likert|\d+-point|rating)\b.{0,20}\bsingle\b", re.I)


def _integer_scale(g: dict, text: str) -> tuple[bool, int | None]:
    """Is this mean built from whole-number responses? Only with a verbatim scale description as evidence:
    either the model says so, or code sees a single Likert/k-point/rating item (then items = 1)."""
    sq = g.get("scale_quote") or ""
    if not _verbatim(sq, text):
        return False, g.get("items")
    if SINGLE_ITEM_RE.search(sq):
        return True, 1
    return bool(g.get("integer_valued")), g.get("items")


def _sig(f: dict) -> tuple:
    """Identity of a checked number, independent of how much surrounding text was quoted.
    Models quote whole sentences (often holding several numbers), so quote text can't be the key."""
    k = f["kind"]
    try:
        if k == "statcheck":
            return k, f["test"], round(abs(C._num(f["stat"])), 6), round(float(f["p"]), 6)
        if k == "percent":
            return k, int(f["x"]), int(f["n"]), round(float(f["pct"]), 6)
        if k == "grim":
            return k, str(f["mean"]).strip(), str(f["n"])
        if k == "arithmetic":
            return k, round(C._num(f["claimed"]), 9)
    except (KeyError, TypeError, ValueError):
        pass
    return k, re.sub(r"\s+", "", f["quote"])[:30]


# ---------------------------------------------------------------- review (model proposes, code already decided)

TRIAGE_SYS = """You triage automated consistency flags in a scientific paper. Code has already recomputed each number; do not dispute the arithmetic.
For each flag, give the most plausible benign explanations (typo, transcription, rounding convention, different test than reported, corrected vs uncorrected df) and say what an author would need to check.
Return ONLY JSON: {"flags": [{"id": int, "explanations": [str], "check": str}]}. Be neutral, never accusatory."""

REVIEW_SYS = """You are a careful senior methodologist. Some recomputed numbers in a paper may change a conclusion.
For each flag write (1) one sentence on whether it could affect the paper's conclusion, given the surrounding claims, and (2) a short, polite query to the authors (2-3 sentences) asking them to confirm the value. Never claim misconduct.
Return ONLY JSON: {"flags": [{"id": int, "impact": str, "author_query": str}]}"""


def review(flags: list[dict], text: str) -> int:
    tokens = 0
    if not flags:
        return 0
    listing = "\n".join(f"[{i}] {f['kind']}: \"{f['quote']}\" -> {f['detail']}" for i, f in enumerate(flags))
    try:
        raw, used = llm.chat("super", TRIAGE_SYS, listing, max_tokens=8000, json_mode=True)
        tokens += used
        for x in llm.parse_json(raw).get("flags", []):
            if isinstance(x, dict) and 0 <= int(x.get("id", -1)) < len(flags):
                flags[int(x["id"])]["triage"] = {"explanations": x.get("explanations", [])[:3], "check": x.get("check", "")}
    except Exception as e:
        print("triage failed", e)
    serious = [i for i, f in enumerate(flags) if f.get("severity") == "decision"]
    if serious:
        ctx = []
        for i in serious:
            f = flags[i]
            pos = text.find(f["quote"][:40])
            ctx.append(f"[{i}] {f['detail']}\nContext: …{text[max(0, pos - 600): pos + 600]}…")
        try:
            raw, used = llm.chat("ultra", REVIEW_SYS, "\n\n".join(ctx), max_tokens=8000, json_mode=True)
            tokens += used
            for x in llm.parse_json(raw).get("flags", []):
                if isinstance(x, dict) and int(x.get("id", -1)) in serious:
                    flags[int(x["id"])]["review"] = {"impact": x.get("impact", ""), "author_query": x.get("author_query", "")}
        except Exception as e:
            print("review failed", e)
    return tokens


# ---------------------------------------------------------------- Tavily preregistration check

PREREG_RE = [
    (re.compile(r"osf\.io/[a-z0-9]{5}\b", re.I), lambda m: "https://" + m.group(0)),
    (re.compile(r"aspredicted\.org/[\w./-]+", re.I), lambda m: "https://" + m.group(0).rstrip(".")),
    (re.compile(r"\bNCT\d{8}\b"), lambda m: f"https://clinicaltrials.gov/study/{m.group(0)}"),
    (re.compile(r"\bISRCTN\d{8}\b"), lambda m: f"https://www.isrctn.com/{m.group(0)}"),
]

PREREG_SYS = """Compare a preregistration/registry record with what the paper reports. Return ONLY JSON:
{"prereg_sample_size": int|null, "prereg_primary_outcome": str|null, "sample_size_match": bool|null, "outcome_match": bool|null, "summary": str (1-2 neutral sentences)}
Use null when the registry text doesn't state it."""


def prereg_check(text: str, paper: dict) -> tuple[dict, int]:
    links = []
    for pat, fn in PREREG_RE:
        for m in pat.finditer(text):
            u = fn(m)
            if u not in links:
                links.append(u)
    res = {"links": links[:3], "status": "none", "detail": "No preregistration or trial-registry link found in the paper."}
    if not links:
        return res, 0
    tk = os.getenv("TAVILY_API_KEY")
    if not tk:
        return {**res, "status": "unchecked", "detail": "Registry links found; Tavily key not configured."}, 0
    try:
        r = httpx.post("https://api.tavily.com/extract", json={"urls": links[:3]},
                       headers={"Authorization": f"Bearer {tk}"}, timeout=60)
        pages = [x.get("raw_content", "")[:8000] for x in r.json().get("results", [])]
    except Exception as e:
        return {**res, "status": "error", "detail": f"Tavily extract failed: {e}"}, 0
    if not any(pages):
        return {**res, "status": "unreadable", "detail": "Tavily couldn't read the registry page(s)."}, 0
    user = (f"PAPER reports sample size: {paper.get('sample_size')}\nPAPER primary outcome: {paper.get('primary_outcome')}\n\n"
            + "\n\n---\n\n".join(f"REGISTRY {links[i]}:\n{p}" for i, p in enumerate(pages)))
    try:
        raw, used = llm.chat("lightning", PREREG_SYS, user, max_tokens=800, json_mode=True, think=False)
        d = llm.parse_json(raw)
    except Exception as e:
        return {**res, "status": "error", "detail": f"Comparison failed: {e}"}, 0
    mismatch = d.get("sample_size_match") is False or d.get("outcome_match") is False
    return {**res, **d, "status": "mismatch" if mismatch else "match", "detail": d.get("summary", "")}, used


# ---------------------------------------------------------------- orchestration

def audit(text: str, meta: dict | None = None, use_llm: bool = True) -> dict:
    meta = meta or {}
    findings = C.find_stats(text) + C.find_percents(text) + C.find_arithmetic(text)
    tokens, notes = 0, []
    extracted = {}
    if use_llm and llm.key():
        try:
            extracted, used = nemotron_extract(text)
            tokens += used
        except Exception as e:
            notes.append(f"Nemotron extraction unavailable ({e}); regex checks only.")
        seen = {_sig(f) for f in findings}

        def add(r, q):
            if not _verbatim(q, text) or _sig(r) in seen:
                return  # drop hallucinated quotes and numbers the regex already checked
            seen.add(_sig(r))
            findings.append({**r, "source": "nemotron"})

        for s in extracted.get("stats", []):
            try:
                add(C.check_stat(s["test"], s["stat"], s.get("df1"), s.get("df2"), s.get("p_op", "="), s["p"], s["quote"],
                                 bool(C.ADJ_RE.search(text))), s["quote"])
            except Exception:
                pass
        for g in extracted.get("grim", []):
            if not MEAN_RE.search(str(g.get("quote", ""))):
                continue  # GRIM is about means; models sometimes list medians or other numbers here
            integer, items = _integer_scale(g, text)
            add(C.check_grim(g.get("mean"), g.get("n"), items, integer, g.get("quote", "")), g.get("quote", ""))
        for p in extracted.get("percents", []):
            try:
                add(C.check_percent(p["x"], p["n"], str(p["pct"]), p["quote"]), p["quote"])
            except Exception:
                pass
        for a in extracted.get("arithmetic", []):
            try:
                add(C.check_arithmetic(a["operands"], a.get("op", "multiply"), a["claimed"], a["quote"]), a["quote"])
            except Exception:
                pass
    elif use_llm:
        notes.append("NEBIUS_API_KEY not set; regex checks only.")

    flags = [f for f in findings if f["status"] == "flag"]
    flags.sort(key=lambda f: f.get("severity") != "decision")
    if use_llm and llm.key() and flags:
        tokens += review(flags, text)

    prereg, used = (prereg_check(text, extracted) if use_llm else ({"status": "skipped", "links": []}, 0))
    tokens += used
    counts = {s: sum(f["status"] == s for f in findings) for s in ("ok", "flag", "not_checkable")}
    return {"meta": meta, "counts": {**counts, "checked": counts["ok"] + counts["flag"],
                                     "decision": sum(f.get("severity") == "decision" for f in flags)},
            "flags": flags, "findings": findings, "prereg": prereg,
            "models": llm.models() if llm.key() else {}, "tokens": tokens, "notes": notes}
