"""Offline tests of how Nemotron's extraction is merged with the regex checks (no API calls)."""
from erratum import llm, pipeline as P

TEXT = open("demos/synthetic.txt").read()
SENT = ("Wellbeing after the intervention was higher in the journaling condition (M = 5.19, SD = 1.02, n = 32) "
        "than in the control condition (M = 4.73, SD = 1.11, n = 17)")
PCT = "Of the 64 participants, 41 were women (62.5%), and 12 of 64 (21.9%) reported prior journaling experience."

# Shape of a real Nemotron Lightning answer: whole-sentence quotes, % signs, scale described in Methods.
EXTRACTED = {
    "grim": [
        {"quote": SENT, "mean": "5.19", "n": 32, "scale_quote": "a single 7-point Likert item", "items": 1, "integer_valued": False},
        {"quote": SENT, "mean": "4.73", "n": 17, "scale_quote": "a single 7-point Likert item", "items": 1, "integer_valued": False},
        {"quote": "34,700 ng/day median intake", "mean": "34700", "n": None, "scale_quote": None, "items": None, "integer_valued": False},
    ],
    "percents": [{"quote": PCT, "x": 41, "n": 64, "pct": "62.5%"}, {"quote": PCT, "x": 12, "n": 64, "pct": "21.9%"}],
    "arithmetic": [{"quote": "Each participant received a booklet costing $3.50; across the full sample this came to 64 × 3.50 dollars = 22.40 dollars.",
                    "operands": [{"value": 64, "unit": "participants"}, {"value": 3.5, "unit": "dollars"}], "op": "multiply",
                    "claimed": {"value": 22.4, "unit": "dollars"}}],
    "stats": [{"quote": "A two-way ANOVA showed an interaction between condition and gender, F(1, 60) = 3.21, p = .03.",
               "test": "F", "stat": "3.21", "df1": "1", "df2": "60", "p_op": "=", "p": ".03"}],
    "sample_size": 64, "primary_outcome": None,
}


def run(monkeypatch, extracted=EXTRACTED):
    monkeypatch.setattr(llm, "key", lambda: "test")
    monkeypatch.setattr(llm, "models", lambda: {})
    monkeypatch.setattr(P, "nemotron_extract", lambda text: (extracted, 0))
    monkeypatch.setattr(P, "review", lambda flags, text: 0)
    return P.audit(TEXT)


def test_finds_all_five_planted_errors(monkeypatch):
    rep = run(monkeypatch)
    flagged = {f["detail"].split(",")[0] for f in rep["flags"]}
    assert len(rep["flags"]) == 5, flagged
    assert any("4.73" in f["detail"] and f["kind"] == "grim" for f in rep["flags"])
    assert any(f["kind"] == "percent" and "41/64" in f["detail"] for f in rep["flags"])


def test_no_duplicates_when_model_quotes_whole_sentences(monkeypatch):
    rep = run(monkeypatch)
    assert sum(f["kind"] == "statcheck" and "3.21" in f["quote"] for f in rep["findings"]) == 1
    assert sum(f["kind"] == "arithmetic" and "22.40" in f["quote"] for f in rep["findings"]) == 1
    assert sum(f["kind"] == "percent" and "12/64" in f["detail"] for f in rep["findings"]) == 1


def test_grim_needs_verbatim_scale_evidence(monkeypatch):
    fake = {**EXTRACTED, "grim": [{**EXTRACTED["grim"][1], "scale_quote": "a 7-point Likert item invented by the model", "integer_valued": True}]}
    rep = run(monkeypatch, fake)
    g = [f for f in rep["findings"] if f["kind"] == "grim"]
    assert g and g[0]["status"] == "not_checkable"


def test_non_means_are_not_grim_candidates(monkeypatch):
    rep = run(monkeypatch)
    assert not any("34,700" in f["quote"] for f in rep["findings"])
