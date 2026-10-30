"""Deterministic checkers. Code decides; models only propose.

Every checker returns a dict with:
  kind, quote, status in {"ok", "flag", "not_checkable"}, detail, severity (flags only).
Missing preconditions -> "not_checkable", never a flag.
"""
from __future__ import annotations

import math
import re

from scipy import stats as st

ALPHA = 0.05


def _decimals(s: str) -> int:
    s = str(s).strip()
    return len(s.split(".")[1]) if "." in s else 0


def _num(s) -> float:
    return float(str(s).replace("−", "-").replace("–", "-").replace(",", ""))


# ---------------------------------------------------------------- statcheck

_P = r"p\s*(?P<pop>[=<>≤≥])\s*(?P<p>0?\.\d+|1(?:\.0+)?)"
_SEP = r"\s*,?\s*"
_NUM = r"(?P<stat>[-−–]?\d*\.?\d+)"
STAT_PATTERNS = {
    "t": re.compile(r"\bt\s*\(\s*(?P<df1>\d+(?:\.\d+)?)\s*\)\s*=\s*" + _NUM + _SEP + _P, re.I),
    "F": re.compile(r"\bF\s*\(\s*(?P<df1>\d+(?:\.\d+)?)\s*,\s*(?P<df2>\d+(?:\.\d+)?)\s*\)\s*=\s*" + _NUM + _SEP + _P),
    "r": re.compile(r"\br\s*\(\s*(?P<df1>\d+)\s*\)\s*=\s*" + _NUM + _SEP + _P),
    "chi2": re.compile(r"(?:χ2|χ²|chi-?squared?|chi2|Χ2)\s*\(\s*(?P<df1>\d+)\s*(?:,\s*N\s*=\s*\d+\s*)?\)\s*=\s*" + _NUM + _SEP + _P, re.I),
    "z": re.compile(r"\bz\s*=\s*" + _NUM + _SEP + _P, re.I),
}


def _p_from(test: str, stat: float, df1, df2) -> float:
    if test == "t":
        return 2 * st.t.sf(abs(stat), df1)
    if test == "F":
        return st.f.sf(stat, df1, df2)
    if test == "r":
        r = max(min(abs(stat), 0.999999), 0.0)
        return 2 * st.t.sf(r * math.sqrt(df1 / (1 - r * r)), df1)
    if test == "chi2":
        return st.chi2.sf(stat, df1)
    if test == "z":
        return 2 * st.norm.sf(abs(stat))
    raise ValueError(test)


def _p_consistent(pop: str, rep: float, rep_dec: int, lo: float, hi: float) -> bool:
    """Is any p in [lo, hi] (range implied by rounding of the statistic) consistent with the report?"""
    if pop in "<≤":
        return lo < rep or math.isclose(lo, rep)
    if pop in ">≥":
        return hi > rep
    half = 0.5 * 10 ** -rep_dec if rep_dec else 0.5
    return not (hi < rep - half - 1e-12 or lo > rep + half + 1e-12)


def check_stat(test, stat_s, df1, df2, pop, p_s, quote, adjust_ok: bool = False) -> dict:
    out = {"kind": "statcheck", "test": test, "quote": quote.strip(), "stat": str(stat_s).strip(), "p": str(p_s).strip()}
    if test in ("t", "F", "r", "chi2") and not df1:
        return {**out, "status": "not_checkable", "detail": "Degrees of freedom missing."}
    if test == "F" and not df2:
        return {**out, "status": "not_checkable", "detail": "F needs two df."}
    stat = _num(stat_s)
    d1 = float(df1) if df1 else None
    d2 = float(df2) if df2 else None
    sd = _decimals(stat_s)
    half = 0.5 * 10 ** -sd if sd else 0.5
    a, b = max(abs(stat) - half, 0.0), abs(stat) + half
    p_hi, p_lo = _p_from(test, a, d1, d2), _p_from(test, b, d1, d2)
    p_mid = _p_from(test, stat, d1, d2)
    rep, rep_dec = float(p_s), _decimals(p_s)
    out.update(computed_p=round(p_mid, 5), reported=f"p {pop} {p_s}")

    if _p_consistent(pop, rep, rep_dec, p_lo, p_hi):
        return {**out, "status": "ok", "detail": f"Recomputed p = {p_mid:.4f}; consistent with the reported value."}
    if test in ("t", "z", "r") and _p_consistent(pop, rep, rep_dec, p_lo / 2, p_hi / 2):
        return {**out, "status": "ok", "one_tailed": True,
                "detail": f"Two-tailed p = {p_mid:.4f}. Consistent if one-tailed (p = {p_mid / 2:.4f}); the paper doesn't say."}

    # Multiple-comparison adjustment: reported p = k × computed p (Bonferroni), or capped at 1.
    if adjust_ok and pop == "=" and rep > p_mid > 0:
        if rep >= 0.999:
            return {**out, "status": "ok", "adjusted": True,
                    "detail": f"Unadjusted p = {p_mid:.4f}. p = 1 is consistent only with a multiple-comparison adjustment capped at 1."}
        for k in range(2, 21):
            if _p_consistent("=", rep, rep_dec, min(p_lo * k, 1), min(p_hi * k, 1)):
                return {**out, "status": "ok", "adjusted": True,
                        "detail": f"Unadjusted p = {p_mid:.4f}. Consistent if Bonferroni-adjusted for {k} comparisons (p × {k} = {min(p_mid * k, 1):.4f})."}

    rep_sig = pop in "=<≤" and rep <= ALPHA
    decision = rep_sig != (p_mid < ALPHA)
    dfs = ", ".join(x for x in (df1, df2) if x)
    return {**out, "status": "flag", "severity": "decision" if decision else "minor",
            "detail": (f"Recomputed p = {p_mid:.4f} from {test}{f'({dfs})' if dfs else ''} = {stat_s}, but the paper reports p {pop} {p_s}."
                       + (" The corrected p is on the other side of α = .05, so the conclusion changes." if decision else ""))}


ADJ_RE = re.compile(r"bonferroni|holm|šidák|sidak|adjusted p|p[- ]?adj|corrected for multiple|multiple comparisons?", re.I)


def find_stats(text: str) -> list[dict]:
    res, seen = [], set()
    adj = bool(ADJ_RE.search(text))
    for test, pat in STAT_PATTERNS.items():
        for m in pat.finditer(text):
            if any(s <= m.start() < e for s, e in seen):
                continue
            seen.add(m.span())
            g = m.groupdict()
            res.append({**check_stat(test, g["stat"], g.get("df1"), g.get("df2"), g["pop"], g["p"], m.group(0), adj),
                        "span": list(m.span()), "source": "regex"})
    return res


# ---------------------------------------------------------------- GRIM

def check_grim(mean_s, n, items, integer_valued, quote) -> dict:
    out = {"kind": "grim", "quote": str(quote).strip(), "mean": str(mean_s), "n": n}
    if not integer_valued:
        return {**out, "status": "not_checkable", "detail": "Measure isn't integer-valued, so GRIM doesn't apply."}
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return {**out, "status": "not_checkable", "detail": "Per-cell n not reported alongside the mean."}
    k = int(items or 1)
    d = _decimals(mean_s)
    N = n * k
    if d == 0 or N >= 10 ** d:
        return {**out, "status": "not_checkable",
                "detail": f"n × items = {N} is too large for GRIM at {d} decimal(s); every mean is achievable."}
    m = _num(mean_s)
    half = 0.5 * 10 ** -d
    lo_t, hi_t = math.ceil((m - half) * N - 1e-9), math.floor((m + half) * N + 1e-9)
    if lo_t <= hi_t:
        return {**out, "status": "ok", "detail": f"Achievable: {lo_t}/{N} = {lo_t / N:.{d + 2}f}."}
    near = sorted({round(t / N, d) for t in (math.floor(m * N), math.ceil(m * N))})
    return {**out, "status": "flag", "severity": "minor",
            "detail": (f"Impossible mean. With n = {n}" + (f" and {k} items" if k > 1 else "")
                       + f", no integer total gives {mean_s}; nearest achievable: " + " or ".join(f"{x:.{d}f}" for x in near) + ".")}


# ---------------------------------------------------------------- percentages

PCT_RE = re.compile(r"(?P<x>\d+)\s*(?:/|of|out of)\s*(?P<n>\d+)\s*(?:[a-z]+\s*)?\(\s*(?P<p>\d+(?:\.\d+)?)\s*%\s*\)", re.I)


def check_percent(x, n, pct_s, quote) -> dict:
    pct_s = str(pct_s).strip().rstrip("%").strip()  # models often copy the % sign
    x, n = int(x), int(n or 0)
    out = {"kind": "percent", "quote": str(quote).strip(), "x": x, "n": n, "pct": pct_s}
    if not n:
        return {**out, "status": "not_checkable", "detail": "Denominator missing."}
    d = _decimals(pct_s)
    true, pct = 100 * x / n, float(pct_s)
    tol = 0.5 * 10 ** -d + 1e-9
    if abs(true - pct) <= tol:
        return {**out, "status": "ok", "detail": f"{x}/{n} = {true:.{d + 1}f}%."}
    if 0 <= true - pct < 2 * tol:
        return {**out, "status": "ok", "detail": f"{x}/{n} = {true:.{d + 1}f}%; consistent if truncated rather than rounded."}
    return {**out, "status": "flag", "severity": "minor", "detail": f"{x}/{n} = {true:.{d + 1}f}%, but the paper reports {pct_s}%."}


def find_percents(text: str) -> list[dict]:
    return [{**check_percent(m["x"], m["n"], m["p"], m.group(0)), "span": list(m.span()), "source": "regex"}
            for m in PCT_RE.finditer(text)]


# ---------------------------------------------------------------- unit-aware arithmetic

_ureg = None


def _u():
    global _ureg
    if _ureg is None:
        import pint
        _ureg = pint.UnitRegistry()
    return _ureg


def _clean_unit(u) -> str:
    if not u:
        return "dimensionless"
    u = re.sub(r"\b(bw|b\.w\.|body ?weight|BW)\b", "", str(u))
    u = u.replace("µ", "u").replace("μ", "u").replace("·", "*").replace("×", "*").replace("per ", "/")
    u = re.sub(r"\s*/\s*", "/", u).strip(" /")
    u = re.sub(r"\bd\b", "day", u)
    return u or "dimensionless"


def _sig_tolerance(v: float) -> float:
    digits = f"{abs(v):.10g}".replace(".", "").lstrip("0").rstrip("0") or "0"
    return min(max(0.5 * 10 ** (1 - max(len(digits), 1)), 0.005), 0.02)


def check_arithmetic(operands, op, claimed, quote) -> dict:
    out = {"kind": "arithmetic", "quote": str(quote).strip(), "claimed": str((claimed or {}).get("value"))}
    try:
        u = _u()
        qs = [_num(o["value"]) * u(_clean_unit(o.get("unit"))) for o in operands]
        if len(qs) < 2:
            return {**out, "status": "not_checkable", "detail": "Fewer than two operands extracted."}
        res = qs[0]
        for q in qs[1:]:
            res = {"multiply": lambda x, y: x * y, "divide": lambda x, y: x / y,
                   "add": lambda x, y: x + y, "subtract": lambda x, y: x - y}[op](res, q)
        claim = _num(claimed["value"]) * u(_clean_unit(claimed.get("unit")))
        res = res.to(claim.units)
    except Exception as e:
        return {**out, "status": "not_checkable", "detail": f"Units couldn't be reconciled ({type(e).__name__})."}
    r, c = float(res.magnitude), float(claim.magnitude)
    unit = f"{claim.units:~}".replace(" ", "")
    out["recomputed"] = f"{r:,.6g} {unit}".strip()
    if c == 0:
        return {**out, "status": "not_checkable", "detail": "Claimed value is zero."}
    rel = abs(r - c) / abs(c)
    if rel <= _sig_tolerance(c):
        return {**out, "status": "ok", "detail": f"Recomputed {out['recomputed']}; matches."}
    ratio = r / c
    k = round(math.log10(abs(ratio))) if ratio > 0 else 0
    slip = k != 0 and abs(math.log10(abs(ratio)) - k) < 0.02
    return {**out, "status": "flag", "severity": "decision" if slip else "minor", "ratio": ratio,
            "detail": (f"Recomputed {out['recomputed']}, but the paper says {c:,.6g}"
                       + (f". Off by exactly ×{10 ** k:g}: a decimal or unit slip." if slip else f" ({rel:.1%} off)."))}


ARITH_RE = re.compile(r"(?P<a>\d[\d,]*\.?\d*)\s*(?P<ua>[A-Za-zµμ/ ]{0,20}?)\s*[×\*]\s*(?P<b>\d[\d,]*\.?\d*)\s*(?P<ub>[A-Za-zµμ/ ]{0,25}?)\s*=\s*(?P<c>\d[\d,]*\.?\d*)\s*(?P<uc>[A-Za-zµμ/]{0,20})")


def find_arithmetic(text: str) -> list[dict]:
    res = []
    for m in ARITH_RE.finditer(text):
        ops = [{"value": m["a"], "unit": m["ua"].strip() or None}, {"value": m["b"], "unit": m["ub"].strip() or None}]
        claimed = {"value": m["c"], "unit": m["uc"].strip() or None}
        r = check_arithmetic(ops, "multiply", claimed, m.group(0))
        if r["status"] == "not_checkable":
            r = check_arithmetic([{"value": o["value"]} for o in ops], "multiply", {"value": m["c"]}, m.group(0))
        res.append({**r, "span": list(m.span()), "source": "regex"})
    return res
