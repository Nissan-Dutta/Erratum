# CLAUDE.md: Erratum (Nebius × NVIDIA Global AI Hackathon)

**Deadline: Fri Oct 30, 2026, 1:00 PM EDT. Submit on Devpost by 11:30 AM EDT.** Track: Best Apps & Agents. Bonus: Best Use of Tavily.
The owner (Nissan) is new to coding. Explain decisions in plain language, keep changes small, and don't let the protected core regress.

Pitch: **Nemotron reads the paper. Math checks every number.**

## Architecture (code decides, models only propose)

```
app.py                FastAPI: GET / (report page), GET /api/demos, GET /api/health, POST /api/audit {input|text|demo}
erratum/checkers.py   Deterministic checks. Returns {kind, quote, status: ok|flag|not_checkable, detail, severity}
                      statcheck (t, F, r, chi2, z, with rounding intervals), one-tailed rule, Bonferroni rule (only if the paper
                      mentions an adjustment: ADJ_RE), GRIM (scope-gated), percentages, unit-aware arithmetic (pint)
erratum/llm.py        Nebius Token Factory client (OpenAI-compatible), daily token cap, auto-discovers Nemotron model ids
erratum/pipeline.py   resolve() Europe PMC ingest -> regex checks -> nemotron_extract() (Lightning, typed JSON, verbatim-quote filter)
                      -> review() (Super triage + Ultra impact/author query) -> prereg_check() (Tavily Extract) -> audit()
static/index.html     Single report page (no build step)
demos/                spatula.txt (paraphrased, already-corrected error), synthetic.txt (planted errors), demos.json
demos/cache/          Precomputed LIVE demo reports (<id>.json) shipped with the code, so demos never depend on the API
bench/bench.py        Planted-error benchmark -> bench/results.json
tests/                pytest unit tests for checkers
```

Hard rules (from the battle plan):
- A missing precondition means **not_checkable**, never a flag. Report how many numbers were checkable.
- Severity is computed by code: does the corrected p cross α = .05, or is the arithmetic off by an exact power of 10?
- Model text in the UI is always labeled "unverified". Never "decided".
- No live accusations. The demos use corrected or synthetic papers only.
- Never commit API keys. Keys come from environment variables only.

## Env vars
`NEBIUS_API_KEY`, `TAVILY_API_KEY` (both optional: without them the regex and code checks still run).
Optional: `MODEL_LIGHTNING`, `MODEL_SUPER`, `MODEL_ULTRA` (otherwise auto-picked from `GET /v1/models` by name),
`NEBIUS_BASE_URL` (default `https://api.tokenfactory.nebius.com/v1`), `DAILY_TOKEN_CAP` (1,500,000), `AUDITS_PER_HOUR` (8), `CACHE_DIR` (/tmp/erratum-cache).

## Commands
```bash
pip install -r requirements.txt pytest
pytest -q tests                                  # 8 tests, all pass
uvicorn app:app --port 7860                      # local app
python -m bench.bench --n 20                     # regex-path benchmark (no keys needed)
python -m bench.bench --n 20 --llm --baseline    # with Nemotron + AI-only baseline (needs NEBIUS_API_KEY)
```
Network needed: www.ebi.ac.uk (Europe PMC), api.tokenfactory.nebius.com, api.tavily.com.

## Status (handoff from the Cowork session, 5:20 AM EDT)

Done:
- [x] Core checkers plus 8 passing unit tests. The spatula slip is caught (60 kg × 7000 ng/kg/day computes to 420,000, but the paper says 42,000: ×10).
- [x] Pipeline: Europe PMC ingest, Nemotron extraction, Super/Ultra review, Tavily preregistration check (live parts written but **not yet run against the real APIs**).
- [x] Report page, rate limit, token cap, demo caching.
- [x] Benchmark, regex path: 20/20 planted p-value errors detected (Wilson 95% CI 0.84–1.00). 6 flags on 337 unmodified numbers (15 before the Bonferroni rule). In a hand-check, 7 of those 15 came from one paper that reports Bonferroni ×10 p-values.
- [x] README (judge-facing), MIT LICENSE, Dockerfile.
- [x] Hugging Face Docker Space is not possible (needs PRO). Use Vercel.

To do, in order:
1. [ ] **Live smoke test.** With NEBIUS_API_KEY set, call `llm.models()` and print the picked ids. Confirm all three roles resolve to Nemotron models; if not, set MODEL_* explicitly. Run `pipeline.audit(open('demos/synthetic.txt').read())`. Expected: Nemotron also finds the GRIM-impossible mean (M = 4.73, n = 17) and 41 women = 62.5% of 64 (actually 64.1%). Fix JSON parsing if the model wraps its output.
2. [ ] **Cache live demo reports.** Save each demo's live audit JSON to `demos/cache/<id>.json` (strip `span`) and commit them. Demos must work even if the API is down.
3. [ ] **Tavily demo.** Find one open-access paper with an OSF or AsPredicted link (Europe PMC search: `"osf.io" AND OPEN_ACCESS:y`). Verify prereg_check() works and add it as a third demo (cached). Keep the wording neutral.
4. [ ] **Baseline.** Run `python -m bench.bench --n 20 --llm --baseline`. Put the Ultra-only recall next to Erratum's recall in the README (Wilson CIs).
5. [ ] **Deploy to Vercel.** FastAPI zero-config (`app.py` exposes `app`). Set the env vars in the Vercel project. Only /tmp is writable (already handled). If the function times out on long papers, add `vercel.json` with maxDuration 300 for the function, or cap chunks in nemotron_extract().
6. [ ] **Verify live.** Both demos, one PMCID (e.g. PMC13354088, a clean paper with all checks consistent), mobile width, dark mode.
7. [ ] **Video shot list and Devpost text.** The draft is in the claude.ai project doc `claude/erratum-ship-status.md`. Video beats (3 min): spatula hook, the problem (statcheck ~50%, GRIM 36/71), live demo, under the hood (name Nemotron Lightning/Super/Ultra on Nebius Token Factory plus Tavily, aloud, with cost per paper), proof (benchmark versus AI-only baseline).

Cut order if behind: UI polish, then the live Tavily call (keep the cached result).
