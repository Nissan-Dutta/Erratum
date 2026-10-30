# Erratum: Devpost text and video shot list

Live app: **https://erratum-nine.vercel.app** · Code: https://github.com/nissan-dutta/erratum · Track: Best Apps & Agents (+ Best Use of Tavily)

---

## Devpost

**Tagline:** Nemotron reads the paper. Math checks every number.

### Inspiration
In 2024 a study of black plastic kitchen utensils made headlines. Its key safety comparison computed 60 kg × 7,000 ng/kg/day as 42,000 ng/day. The right answer is 420,000. The ×10 slip passed peer review and was corrected only after publication. It isn't rare: statcheck found that about half of psychology papers contain at least one p-value that doesn't match its own test statistic, and GRIM found impossible means in 36 of the 71 papers it could test. Asking a chatbot to "find the errors" doesn't fix this. Language models are poor at arithmetic, and a reviewer can't tell their hits from their false alarms.

### What it does
Paste a PMCID, a DOI or text. Erratum finds every number that can be recomputed from other numbers in the paper and recomputes it:
- p-values from t, F, r, χ² and z, with rounding intervals (statcheck-style)
- means against their sample sizes (GRIM)
- percentages against their counts
- stated calculations, unit-aware (pint): the spatula slip is caught as "off by exactly ×10"

Each flag shows the quote, the recomputed value, and whether the corrected number crosses α = .05. That severity is decided by code. Nemotron Super then suggests benign explanations, and for flags that could change a conclusion, Nemotron Ultra drafts a polite query to the authors. Both are labeled *unverified*. If the paper links a preregistration, Tavily reads the registry and code compares the planned N with the reported N.

### How we built it (code decides, models only propose)
| Step | Who | What |
|---|---|---|
| Read | **Nemotron 3.5 Lightning** on Nebius Token Factory (thinking off) | Typed JSON of every checkable number, with verbatim quotes. A regex parser covers APA-style statistics too. |
| Ground | **Code** | Every number Nemotron proposes must be visible in its verbatim quote, with the statistic next to its own p and operator. Otherwise it is set aside, and the count is shown in the report. |
| Decide | **Code** | statcheck, GRIM, percentages, pint arithmetic. A missing precondition gives "not checkable", never a flag. |
| Explain | **Nemotron 3 Super 120B** (reasoning on) | Benign explanations for each flag, labeled unverified. |
| Escalate | **Nemotron 3 Ultra 550B** (reasoning on) | Impact sentence and author query for conclusion-changing flags. |
| Cross-check | **Tavily Extract** (advanced) | Reads OSF / ClinicalTrials.gov registries. Nemotron quotes the planned N, and code verifies the quote and compares. |

FastAPI on Vercel, a single HTML page, no build step. Demo reports are precomputed live runs shipped with the code, so the demo works even if an API is down.

### Challenges we ran into
The first live run on real papers produced false flags. **They came from the model, not the math.** Nemotron read "72%" as 72 out of the whole sample of 240, read an effect size (η²p = 0.35) as 35%, turned "p < .05" into "p = .05", and paired one effect's z with another effect's p. Every number was plausible, and every one was wrong. The fix was structural rather than a better prompt: code now accepts a model-proposed number only if it can see that number in the model's own verbatim quote. Clean papers went back to zero flags, and the planted errors are still caught. The same principle fixed the preregistration check. Exceeding a registered *minimum* sample size isn't a mismatch, and a registry page with no readable text is "unreadable", not something for a model to guess at.

### Accomplishments
- Runs live end to end on **Nemotron 3.5 Lightning, Nemotron 3 Super and Nemotron 3 Ultra via Nebius Token Factory**, plus **Tavily**. A 144k-character paper audits in about 26 s.
- **Planted-error benchmark on 20 real open-access papers: 20/20 detected (95% CI 0.84–1.00).** Nemotron Ultra on its own also scored 20/20. The difference is that Erratum's code path uses **zero model tokens** (Ultra alone used ~18k per paper), and every verdict is a printed recomputation instead of a claim.
- Ultra on its own also raised claims that code recomputes as consistent, including a confident, wrong "Holm-adjusted p should be 0.118" (Holm's step-down rule makes 0.210 correct).
- 9 flags across 341 checked numbers on unmodified papers, each shown with its recomputation; 0 flags on clean papers after grounding.
- 20 offline tests, including the exact false positives Nemotron produced on real papers, so they can't come back.

### What we learned
LLMs are excellent readers and unreliable judges. Splitting the job, so the model finds and quotes the numbers while code verifies and decides, gives you the model's reach without its false alarms. Turning thinking off for pure extraction made Lightning faster and cheaper, and it never got stuck mid-reasoning.

### What's next
Tables and supplementary files; per-study sample sizes for multi-study papers; a browser extension for reviewers; batch audits for journals before publication.

### Built with
NVIDIA Nemotron (3.5 Lightning, 3 Super 120B, 3 Ultra 550B) · Nebius Token Factory · Tavily · Europe PMC · FastAPI · SciPy · pint · Vercel

---

## Cost per paper (measured token use)
| Paper | Size | Tokens (all Nemotron calls) | Wall time |
|---|---|---|---|
| Spatula excerpt (demo) | 766 chars | 2,824 | 12 s |
| Planted-error paper (demo) | 1,233 chars | 5,514 | 30 s |
| PMC13646472 (prereg demo, with Tavily) | 34,811 chars | 10,799 | 22 s |
| PMC13354088 (long real paper) | 143,762 chars | 29,360 | 26 s |
| Benchmark average (20 papers) | full text | ~21,000 | — |

Dollar cost = tokens × Nebius Token Factory list price per model (**fill in from the Nebius price page**; it needs a login, so it wasn't readable from here). Most tokens are Lightning extraction, the cheapest model. Ultra runs only on flags that could change a conclusion.

---

## Video shot list (3:00)
| Time | Shot | Voice-over (say the model names aloud) |
|---|---|---|
| 0:00–0:20 | Headline about black plastic utensils, then the line "60 kg × 7000 ng/kg/day = 42,000 ng/day" | "This multiplication passed peer review. The right answer is ten times bigger." |
| 0:20–0:45 | Statcheck and GRIM numbers on screen | "About half of psychology papers have a p-value that doesn't match its own statistic. GRIM found impossible means in 36 of 71 papers. Asking an AI to find errors gives you false alarms you can't tell apart." |
| 0:45–1:30 | Live app: spatula demo, then the planted-error demo | "Erratum: Nemotron reads the paper, math checks every number." Show the ×10 flag, Ultra's author query, the GRIM-impossible mean, and the one-tailed test that is *not* flagged. |
| 1:30–1:55 | Preregistration demo | "If the paper links a preregistration, Tavily reads the registry; code compares the plan with what was reported, and says 'unclear' rather than guessing." |
| 1:55–2:25 | Architecture table | "Nemotron 3.5 Lightning on Nebius Token Factory extracts the numbers with thinking off. Code grounds and checks every one. Nemotron 3 Super explains flags, Nemotron 3 Ultra drafts author queries, Tavily reads registries. About ten to thirty thousand tokens per paper." |
| 2:25–2:50 | Benchmark slide | "On 20 real papers with planted errors, Erratum caught 20 of 20, and so did Nemotron Ultra on its own. The difference: Erratum's checks cost zero model tokens and show their math. Ultra on its own also confidently flagged numbers that were correct." |
| 2:50–3:00 | Footer line on screen | "A flag is a number that doesn't match the numbers it was computed from. Not an accusation." |
