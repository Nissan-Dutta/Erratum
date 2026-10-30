"""Ingest -> extract (regex + Nemotron Lightning) -> code checks -> Super triage / Ultra review -> Tavily prereg."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

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
    t = root.find(".//article-meta/title-group/article-title")  # not the reference list's titles
    title = " ".join("".join(t.itertext()).split())[:300] if t is not None else None
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
    call = lambda ch: llm.chat("lightning", EXTRACT_SYS, ch, max_tokens=4000, json_mode=True, think=False)
    with ThreadPoolExecutor(4) as ex:  # chunks in parallel: long papers must fit a serverless time limit
        answers = list(ex.map(call, list(_chunks(text))[:4]))
    for raw, used in answers:
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


_NUM_TOKEN = re.compile(r"(?<![\w.,])[-−–]?(?:\d[\d,]*\.?\d*|\.\d+)(?![\w.,]*\d)(?P<pct>\s*%)?")


def _numbers(quote: str) -> tuple[set, set]:
    """Standalone numbers in a quote: (plain numbers, percentages). '42,000' -> 42000; 'F2,276' and 'η2p' don't count."""
    plain, pcts = set(), set()
    for m in _NUM_TOKEN.finditer(quote):
        try:
            v = abs(C._num(m.group(0).replace("%", "").strip().rstrip(",")))
        except ValueError:
            continue
        (pcts if m["pct"] else plain).add(round(v, 9))
    return plain, pcts


def _in(v, nums: set) -> bool:
    try:
        return round(abs(C._num(v)), 9) in nums
    except (TypeError, ValueError):
        return False


_OPS = {"=": "=", "<": "[<≤]", ">": "[>≥]", "≤": "[<≤]", "≥": "[>≥]"}


def _grounded(kind: str, x: dict) -> bool:
    """Models only propose: every number Nemotron hands to a checker must be visible in its verbatim quote.
    Catches invented denominators (72% read as 72/N), effect sizes read as percentages, and p < .05 turned into p = .05."""
    q = str(x.get("quote", ""))
    plain, pcts = _numbers(q)
    try:
        if kind == "stats":
            p = str(x["p"]).strip()
            # the statistic and its own p must be adjacent: no other p-value in between (mediation sentences list several)
            stat = re.escape(str(x["stat"]).strip().lstrip("-−–"))
            p_ok = re.search(stat + r"(?:(?!\bp\s*[=<>≤≥]).){0,80}?\bp\s*" + _OPS.get(x.get("p_op", "="), "=")
                             + r"\s*0?\s*" + re.escape(p.lstrip("0")) + r"(?!\d)", q)
            dfs = [d for d in (x.get("df1"), x.get("df2")) if d not in (None, "")]
            # df may be glued to the test letter ("t133", "F2,276"), which is exactly where the regex misses
            df_ok = all(re.search(r"(?<![\d.])" + re.escape(str(d).strip()) + r"(?![\d.])", q) for d in dfs)
            return bool(p_ok) and _in(x["stat"], plain) and df_ok
        if kind == "percents":
            pct = str(x["pct"]).rstrip("%").strip()
            near = re.search(r"(?<![\w.,])" + re.escape(str(int(x["x"]))) + r"(?![\d.,])[^%]{0,40}?" + re.escape(pct) + r"\s*%", q)
            return bool(near) and _in(x["n"], plain) and _in(pct, pcts)
        if kind == "grim":
            return _in(x["mean"], plain) and _in(x["n"], plain)
        if kind == "arithmetic":
            return all(_in(o["value"], plain) for o in x["operands"]) and _in(x["claimed"]["value"], plain)
    except (KeyError, TypeError, ValueError):
        return False
    return False


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
    (re.compile(r"aspredicted\.org/[\w./?=&-]+", re.I), lambda m: "https://" + m.group(0).rstrip(".")),
    (re.compile(r"\bNCT\d{8}\b"), lambda m: f"https://clinicaltrials.gov/study/{m.group(0)}"),
    (re.compile(r"\bISRCTN\d{8}\b"), lambda m: f"https://www.isrctn.com/{m.group(0)}"),
]

PREREG_SYS = """You read a preregistration or trial-registry record and extract what it plans. You never judge the paper.
Return ONLY JSON:
{"planned_n": int|null (planned total sample size), "planned_n_quote": str|null (verbatim from the registry text, max 200 chars, containing planned_n),
 "planned_n_type": "exact"|"minimum"|"maximum"|"approximate"|null, "primary_outcome": str|null (as registered),
 "outcome_note": str|null (one neutral sentence: does the paper's primary outcome correspond to the registered one?)}
Use null when the registry text doesn't state it. Count participants, not groups, chains or sessions."""


def compare_n(planned: int, kind: str | None, paper_n: int) -> tuple[str, str]:
    """Code decides whether the reported N is consistent with the registered plan."""
    if kind == "minimum":
        ok, plan = paper_n >= planned, f"at least {planned}"
    elif kind == "maximum":
        ok, plan = paper_n <= planned, f"at most {planned}"
    elif kind == "approximate":
        ok, plan = abs(paper_n - planned) <= 0.1 * planned, f"about {planned}"
    else:
        ok, plan = paper_n == planned, f"{planned}"
    if ok:
        return "match", f"Planned N: {plan}. The paper reports N = {paper_n}, consistent with the plan."
    return "differs", (f"Planned N: {plan}. The paper reports N = {paper_n}. Differences can be legitimate "
                       "(exclusions, attrition, stopping rules); the paper's participant flow should explain it.")


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
        # advanced depth renders JavaScript registries (OSF, ClinicalTrials.gov)
        r = httpx.post("https://api.tavily.com/extract", json={"urls": links[:3], "extract_depth": "advanced"},
                       headers={"Authorization": f"Bearer {tk}"}, timeout=90)
        pages = [x.get("raw_content", "")[:20000] for x in r.json().get("results", [])]
    except Exception as e:
        return {**res, "status": "error", "detail": f"Tavily extract failed: {e}"}, 0
    if sum(len(pg) for pg in pages) < 1500:  # e.g. a PDF viewer shell: nothing to compare, so don't let a model guess
        return {**res, "status": "unreadable", "detail": "Tavily reached the registry, but the page holds no readable plan text."}, 0
    user = (f"PAPER primary outcome: {paper.get('primary_outcome')}\n\n"
            + "\n\n---\n\n".join(f"REGISTRY {links[i]}:\n{p}" for i, p in enumerate(pages)))
    try:
        raw, used = llm.chat("lightning", PREREG_SYS, user, max_tokens=800, json_mode=True, think=False)
        d = llm.parse_json(raw)
    except Exception as e:
        return {**res, "status": "error", "detail": f"Registry reading failed: {e}"}, 0
    out = {**res, "outcome_note": d.get("outcome_note"), "registered_outcome": d.get("primary_outcome")}
    # Ground both Ns: the planned N must sit in a verbatim registry quote, the paper's N must appear in the paper.
    q = d.get("planned_n_quote") or ""
    planned = d.get("planned_n")
    if not (isinstance(planned, int) and q and any(_verbatim(q, pg) for pg in pages) and _in(planned, _numbers(q)[0])):
        return {**out, "status": "unclear", "detail": "Tavily read the registry, but no planned sample size could be confirmed in its text."}, used
    paper_n = paper.get("sample_size")
    if not (isinstance(paper_n, int) and _in(paper_n, _numbers(text)[0])):
        return {**out, "status": "unclear", "planned_n": planned, "planned_n_quote": q,
                "detail": f"Registry plans N = {planned}, but the paper's total N couldn't be identified."}, used
    status, detail = compare_n(planned, d.get("planned_n_type"), paper_n)
    return {**out, "status": status, "detail": detail, "planned_n": planned, "planned_n_quote": q, "paper_n": paper_n}, used


# ---------------------------------------------------------------- orchestration

def audit(text: str, meta: dict | None = None, use_llm: bool = True) -> dict:
    meta = meta or {}
    text = C.neutralize_long_numbers(text)  # before any checker or model sees the text
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

        for x in extracted.get("stats", []):
            m = re.match(r"\s*([<>=≤≥])\s*(.+)", str(x.get("p", "")))
            if m:  # model put the operator inside p ("<.05"); split it, grounding still checks it against the quote
                x["p_op"], x["p"] = m.group(1), m.group(2).strip()
        dropped = 0
        for k in ("stats", "grim", "percents", "arithmetic"):
            kept = [x for x in extracted.get(k, []) if _grounded(k, x)]
            dropped += len(extracted.get(k, [])) - len(kept)
            extracted[k] = kept
        if dropped:
            notes.append(f"Grounding: code set aside {dropped} number(s) Nemotron proposed but couldn't show in its verbatim quote.")
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
