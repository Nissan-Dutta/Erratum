---
title: Erratum
emoji: 🔢
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
license: mit
short_description: Nemotron reads the paper. Math checks every number.
---

# Erratum

**Nemotron reads the paper. Math checks every number.**

A multiplication error in a 2024 study of black plastic kitchen utensils (Chemosphere) made it past peer review and into the headlines. The authors computed 60 kg × 7000 ng/kg/day as 42,000 ng/day when it is 420,000, and published a correction later. Statcheck has found that about half of psychology papers contain at least one inconsistent p-value, and GRIM found impossible means in 36 of the 71 papers it could check. Asking an LLM "find the errors" doesn't solve this, because models are bad at arithmetic and produce false positives.

Erratum splits the job:

| Step | Who | What |
|---|---|---|
| Read | **Nemotron Lightning** (Nebius Token Factory) | Typed JSON extraction of every checkable number: test statistics, means with n and item counts, percentages with counts, and stated calculations with units. Also uses a regex fallback for APA-style statistics. **Grounding:** a quote must appear verbatim in the paper, and every number Nemotron hands to a checker must be visible in that quote, with a statistic next to its own p and operator. On real papers this dropped invented denominators ("72%" read as 72/240) and "p < .05" rewritten as "p = .05". |
| Decide | **Code** | statcheck-style p recomputation (t, F, r, χ², z) with rounding intervals; GRIM; percentages against counts; unit-aware arithmetic (pint). |
| Explain | **Nemotron Super** | For each flag, proposes benign explanations (typo, rounding, a different test). These are labeled unverified. |
| Escalate | **Nemotron Ultra** | For flags that could change a conclusion: an impact sentence and a polite draft query to the authors. |
| Cross-check | **Tavily Extract** | Reads the OSF, ClinicalTrials.gov, ISRCTN or AsPredicted registry linked in the paper (advanced extraction renders JavaScript pages). Nemotron quotes the planned N; code checks the quote is really on the registry page and compares it with the paper's N (a planned minimum that was exceeded is not a mismatch). |

**Code tests explanations instead of guessing.** A one-tailed result is reported as "consistent if one-tailed (paper doesn't say)" and is not flagged. A Bonferroni-adjusted p counts as consistent only when the paper itself mentions an adjustment. When a precondition is missing (df, per-cell n, integer-valued measure) the number is reported as **not checkable**, never as a flag. Severity is computed: does the corrected p cross α = .05, or is the arithmetic off by an exact power of ten?

## Evaluation (planted errors, real papers)

`python -m bench.bench --n 20` takes 20 recent open-access papers from Europe PMC, picks a statistic the checker already finds consistent, flips its reported p across α, and re-audits.

- **Recall on planted p-value errors: 20/20 (95% Wilson CI 0.84–1.00).** This measures checking, not extraction: the planted statistic is one the parser already recognized. Extraction coverage is the open problem.
- **Flags on the unmodified papers: 6 across 337 checked numbers.** I hand-checked an earlier run with 15 flags. Seven came from one paper that reports Bonferroni-adjusted p-values (×10, capped at 1). That led to the code-tested adjustment rule above, which removed them without losing any recall. Most of the remaining flags are small rounding-level differences, likely from Welch or Greenhouse–Geisser corrections that the text doesn't state. Each one has to be confirmed by a person.
- An AI-only baseline (Nemotron Ultra asked to "find the statistical errors") runs with `--baseline`.

Full rows: `bench/results.json`.

## Run

```bash
pip install -r requirements.txt
export NEBIUS_API_KEY=...  TAVILY_API_KEY=...       # optional: without them, regex + code checks still run
# optional: MODEL_LIGHTNING / MODEL_SUPER / MODEL_ULTRA (auto-discovered from /v1/models otherwise)
uvicorn app:app --port 7860
pytest -q tests
```

Safety for a public demo: a daily token cap across all users (`DAILY_TOKEN_CAP`), a per-IP rate limit (`AUDITS_PER_HOUR`), and cached demo reports.

## Ethics

A flag means a number doesn't match the numbers it was computed from. It is not an accusation. The demos use a paraphrased excerpt of a published, already-corrected error and a synthetic paper with planted errors. They never accuse a live paper.

MIT licensed.
