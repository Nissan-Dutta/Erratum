"""Planted-error benchmark.

For each open-access paper (Europe PMC), take a statistic the checker already finds consistent,
corrupt its reported p-value across alpha (planted error), re-run the audit, and record whether that
exact statistic is now flagged. Also lists flags on the unmodified paper for hand-checked precision.

Optional AI-only baseline (--baseline): ask Nemotron Ultra to "find the statistical errors" in the
same planted paper; scored as detected if it quotes the planted statistic.

Usage: python -m bench.bench [--n 20] [--llm] [--baseline]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from pathlib import Path

import httpx

from erratum import checkers as C, llm, pipeline as P

OUT = Path(__file__).parent / "results.json"
QUERIES = ['JOURNAL:"Collabra"', 'JOURNAL:"Royal Society Open Science"', 'JOURNAL:"PLoS One" AND "preregistered"',
           'JOURNAL:"Frontiers in Psychology" AND "experiment"']


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def candidates() -> list[str]:
    ids = []
    for q in QUERIES:
        r = httpx.get(f"{P.EPMC}/search", params={"query": q + " AND OPEN_ACCESS:y AND SRC:PMC", "format": "json",
                                                  "pageSize": 30, "resultType": "lite"}, timeout=30)
        ids += [h["pmcid"] for h in r.json()["resultList"]["result"] if h.get("pmcid")]
    random.Random(7).shuffle(ids)
    return ids


def corrupt_p(f: dict) -> str | None:
    q = f["quote"]
    m = re.search(r"p\s*([=<>≤≥])\s*(0?\.\d+)", q)
    if not m:
        return None
    new = ".003" if f.get("computed_p", 0.5) > 0.05 else ".41"   # flip across alpha
    return q[: m.start()] + f"p = {new}" + q[m.end():]


def run(n: int, use_llm: bool, baseline: bool):
    rows = []
    for pid in candidates():
        if len(rows) >= n:
            break
        try:
            paper = P.resolve(pid)
        except Exception:
            continue
        text = paper["text"]
        base = P.audit(text, use_llm=False)
        ok = [f for f in base["findings"] if f["kind"] == "statcheck" and f["status"] == "ok" and not f.get("one_tailed")]
        if len(ok) < 2:
            continue
        target = random.Random(pid).choice(ok)
        mutated = corrupt_p(target)
        if not mutated:
            continue
        planted_text = text.replace(target["quote"], mutated, 1)
        rep = P.audit(planted_text, use_llm=use_llm)
        key = re.sub(r"\s", "", mutated)[:25]
        hit = any(f["status"] == "flag" and re.sub(r"\s", "", f["quote"])[:25] == key for f in rep["findings"])
        row = {"pmcid": pid, "title": paper["title"][:90], "planted": mutated, "original": target["quote"],
               "detected": hit, "unmodified_flags": [f["quote"] + " | " + f["detail"] for f in base["flags"]],
               "checked_unmodified": base["counts"]["checked"], "flags_planted": len(rep["flags"]), "tokens": rep["tokens"]}
        if baseline and llm.key():
            # Fair baseline: Ultra with reasoning on and room to finish, and the planted statistic inside its window.
            pos = planted_text.find(mutated)
            start = max(0, min(pos - 30000, len(planted_text) - 60000))
            prompt = ("Find any statistical reporting errors (p-values inconsistent with their test statistics) in this paper. "
                      "Quote each erroneous statistic verbatim.\n\n" + planted_text[start:start + 60000])
            try:
                raw, used = llm.chat("ultra", "You are an expert statistical reviewer.", prompt, max_tokens=16000)
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
                row["baseline_detected"] = key[:18] in re.sub(r"\s", "", raw)
                row["baseline_finish"], row["baseline_tokens"] = llm.last.finish, used
                # Code recomputes every statistic Ultra quoted: consistent ones are false alarms.
                claims = [c for c in C.find_stats(raw) if re.sub(r"\s", "", c["quote"])[:25] != key]
                row["baseline_other_claims"] = len(claims)
                row["baseline_false_alarms"] = [c["quote"] for c in claims if c["status"] == "ok"]
            except Exception as e:
                row["baseline_error"] = str(e)[:200]
        rows.append(row)
        print(f"{pid}: detected={hit} baseline={row.get('baseline_detected')} unmodified_flags={len(row['unmodified_flags'])}", flush=True)

    k = sum(r["detected"] for r in rows)
    summary = {"papers": len(rows), "planted_detected": k, "recall": round(k / len(rows), 3) if rows else 0,
               "recall_ci95": wilson(k, len(rows)),
               "flags_on_unmodified": sum(len(r["unmodified_flags"]) for r in rows),
               "numbers_checked_unmodified": sum(r["checked_unmodified"] for r in rows)}
    b = [r["baseline_detected"] for r in rows if "baseline_detected" in r]
    if b:
        summary.update(baseline_n=len(b), baseline_detected=sum(b), baseline_recall=round(sum(b) / len(b), 3),
                       baseline_ci95=wilson(sum(b), len(b)),
                       baseline_other_claims=sum(r.get("baseline_other_claims", 0) for r in rows),
                       baseline_false_alarms=sum(len(r.get("baseline_false_alarms", [])) for r in rows),
                       baseline_truncated=sum(r.get("baseline_finish") == "length" for r in rows),
                       erratum_flags_on_planted_papers=sum(r["flags_planted"] for r in rows))
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--n", type=int, default=20)
    a.add_argument("--llm", action="store_true")
    a.add_argument("--baseline", action="store_true")
    x = a.parse_args()
    run(x.n, x.llm, x.baseline)
