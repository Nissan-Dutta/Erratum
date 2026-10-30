from erratum import checkers as C


def test_statcheck_consistent():
    assert C.check_stat("t", "2.20", "28", None, "=", ".036", "q")["status"] == "ok"


def test_statcheck_decision_error():
    r = C.check_stat("F", "3.21", "1", "60", "=", ".03", "q")
    assert r["status"] == "flag" and r["severity"] == "decision"


def test_one_tailed_is_not_a_flag():
    r = C.check_stat("t", "1.72", "62", None, "=", ".045", "q")
    assert r["status"] == "ok" and r["one_tailed"]


def test_bonferroni_only_when_paper_mentions_it():
    assert C.check_stat("t", "3.13", "18", None, "=", "0.058", "q")["status"] == "flag"
    assert C.check_stat("t", "3.13", "18", None, "=", "0.058", "q", adjust_ok=True)["status"] == "ok"


def test_grim():
    assert C.check_grim("3.48", 17, 1, True, "q")["status"] == "flag"
    assert C.check_grim("3.44", 25, 1, True, "q")["status"] == "ok"
    assert C.check_grim("3.44", 250, 1, True, "q")["status"] == "not_checkable"
    assert C.check_grim("3.48", 17, 1, False, "q")["status"] == "not_checkable"


def test_percent():
    assert C.check_percent(12, 64, "21.9", "q")["status"] == "flag"
    assert C.check_percent(23, 51, "45.1", "q")["status"] == "ok"


def test_spatula_unit_slip():
    r = C.check_arithmetic([{"value": 60, "unit": "kg"}, {"value": 7000, "unit": "ng/kg bw/day"}], "multiply",
                           {"value": 42000, "unit": "ng/day"}, "q")
    assert r["status"] == "flag" and r["severity"] == "decision" and abs(r["ratio"] - 10) < 1e-6


def test_units_convert():
    r = C.check_arithmetic([{"value": 60, "unit": "kg"}, {"value": 7, "unit": "µg/kg/day"}], "multiply",
                           {"value": 0.42, "unit": "mg/day"}, "q")
    assert r["status"] == "ok"


def test_percent_sign_copied_by_model():
    assert C.check_percent(41, 64, "62.5%", "q")["status"] == "flag"
