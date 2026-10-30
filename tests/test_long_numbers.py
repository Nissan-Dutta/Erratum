"""Regression tests for the long-digit-run slowdown (a 5,000-digit paste used to hold a worker for minutes)."""
import threading

from erratum import checkers as C, pipeline as P

BUDGET_S = 10


def _audit_within(text: str, seconds: float = BUDGET_S) -> dict:
    out: dict = {}

    def run():
        try:
            out["rep"] = P.audit(text, use_llm=False)
        except Exception as e:  # surfaced below so a crash fails the test with a readable message
            out["error"] = e

    worker = threading.Thread(target=run, daemon=True)  # a hung old-code run must not block pytest exit
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"audit did not finish within {seconds} s"
    assert "error" not in out, f"audit crashed: {out['error']!r}"
    return out["rep"]


def test_five_thousand_digit_run_completes_quickly():
    _audit_within("1" * 5000 + " × 2 = 3. Also 12/64 (21.9%) reported prior experience.")


def test_long_run_before_percentage_does_not_crash():
    # int("1" * 5000) raises ValueError (Python's 4,300-digit limit); this used to reach the user as a 500.
    _audit_within("1" * 5000 + "/3 (4%)")


def test_comma_separated_long_run_completes_quickly():
    _audit_within("1," * 5000 + " × 2 = 3")


def test_long_run_is_replaced_before_checking():
    assert C.neutralize_long_numbers("a " + "9" * 5000 + " b") == "a [long number] b"


def test_normal_numbers_are_untouched():
    text = "Mean 42,000 ng/day, p = 0.0000001, n = 1,234,567.89, and 29-digit 12345678901234567890123456789."
    assert C.neutralize_long_numbers(text) == text


def test_demo_papers_are_unchanged():
    for name in ("spatula", "synthetic"):
        text = open(f"demos/{name}.txt").read()
        assert C.neutralize_long_numbers(text) == text


def test_flags_on_normal_text_still_found():
    rep = _audit_within("Of the 64 participants, 12 of 64 (21.9%) reported prior experience. "
                        "Padding " + "1" * 5000 + " then 60 kg × 7000 ng/kg bw/day = 42,000 ng/day.")
    assert any(f["kind"] == "percent" and f["status"] == "flag" for f in rep["findings"])
    assert any(f["kind"] == "arithmetic" and f["status"] == "flag" for f in rep["findings"])
