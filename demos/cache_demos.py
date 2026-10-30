"""Precompute live demo reports into demos/cache/<id>.json, so demos never depend on the API.

Usage: python demos/cache_demos.py [demo_id ...]     (needs NEBIUS_API_KEY; TAVILY_API_KEY for prereg)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from erratum import llm, pipeline  # noqa: E402

OUT = ROOT / "demos" / "cache"


def demo_input(d: dict) -> tuple[str, dict]:
    """Same text and meta that app.py uses for a demo."""
    if d.get("pmcid"):
        p = pipeline.resolve(d["pmcid"])
        return p["text"], {"title": p["title"], "pmcid": p["pmcid"], "doi": p["doi"], "note": d.get("note")}
    return (ROOT / "demos" / d["file"]).read_text(), {"title": d["label"], "note": d.get("note")}


def main(ids: list[str]):
    if not llm.key():
        sys.exit("NEBIUS_API_KEY not set: a cached demo must be a live report.")
    OUT.mkdir(exist_ok=True)
    for d in json.loads((ROOT / "demos" / "demos.json").read_text()):
        if ids and d["id"] not in ids:
            continue
        text, meta = demo_input(d)
        text = text[:200_000]
        t0 = time.time()
        rep = pipeline.audit(text, meta)
        rep["seconds"], rep["chars"] = round(time.time() - t0, 1), len(text)
        for f in rep["findings"]:
            f.pop("span", None)
        (OUT / f"{d['id']}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
        print(f"{d['id']}: {rep['counts']} tokens={rep['tokens']} {rep['seconds']}s notes={rep['notes']}")


if __name__ == "__main__":
    main(sys.argv[1:])
