"""PREVENT base engine: agreement with an independent implementation, and eligibility.

Agreement with preventr is implementation agreement, not validation. Milestone 3A acceptance
needs authoritative reference outputs (test_reference_cases.py)."""

import csv
from pathlib import Path

import pytest

from app.risk.prevent import AGE_RANGE, RANGES, PreventInputs, estimate, estimate_all, required_inputs

DATA = Path(__file__).parent / "data"


def _row_inputs(r):
    return PreventInputs(
        sex=r["sex"], age=float(r["age"]), total_c=float(r["total_c"]), hdl_c=float(r["hdl_c"]),
        sbp=float(r["sbp"]), egfr=float(r["egfr"]), bmi=float(r["bmi"]),
        diabetes=r["dm"] == "1", smoking=r["smoking"] == "1", bp_tx=r["bp_tx"] == "1", statin=r["statin"] == "1",
    )


def test_agrees_with_preventr_on_random_profiles():
    rows = list(csv.DictReader(open(DATA / "preventr_crosscheck_cases.csv")))
    assert len(rows) >= 1000
    worst = 0.0
    for r in rows:
        x = _row_inputs(r)
        for outcome in ("total_cvd", "ascvd", "heart_failure"):
            res = estimate(x, int(r["horizon"]), outcome)
            assert res.probability is not None, (r["case_id"], res.ineligible_reasons)
            worst = max(worst, abs(res.probability - float(r[outcome])))
    assert worst < 1e-9, worst


BASE = PreventInputs(sex="male", age=50, total_c=200, hdl_c=50, sbp=120, egfr=90, bmi=25,
                     diabetes=False, smoking=False, bp_tx=False, statin=False)


def _with(**kw):
    return PreventInputs(**{**BASE.__dict__, **kw})


@pytest.mark.parametrize("horizon", [10, 30])
def test_age_boundaries_both_sides(horizon):
    lo, hi = AGE_RANGE[horizon]
    for age, ok in ((lo, True), (lo - 1, False), (hi, True), (hi + 1, False), (29.9, False)):
        res = estimate(_with(age=age), horizon, "total_cvd")
        assert (res.probability is not None) == ok, (horizon, age, res.ineligible_reasons)


@pytest.mark.parametrize("name", sorted(RANGES))
def test_input_range_boundaries_both_sides(name):
    lo, hi = RANGES[name]
    step = 0.1 if name == "bmi" else 1
    outcome = "heart_failure" if name == "bmi" else "total_cvd"
    extra = {"total_c": 300} if name == "hdl_c" else {}
    top = [(hi - step, True), (hi, False)] if name == "bmi" else [(hi, True), (hi + step, False)]  # BMI "<40"
    for value, ok in [(lo, True), (lo - step, False), *top]:
        res = estimate(_with(**extra, **{name: value}), 10, outcome)
        assert (res.probability is not None) == ok, (name, value, res.ineligible_reasons)
        if not ok:
            assert any(name in reason for reason in res.ineligible_reasons)


def test_missing_input_is_never_imputed():
    res = estimate(_with(sbp=None), 10, "ascvd")
    assert res.probability is None and res.ineligible_reasons == ["sbp missing"]
    res = estimate(_with(smoking=None), 10, "ascvd")
    assert res.probability is None and "smoking missing" in res.ineligible_reasons


def test_bmi_is_required_only_where_it_has_a_coefficient():
    assert "bmi" in required_inputs("male", 10, "heart_failure")
    no_bmi = _with(bmi=None)
    by_outcome = {r.outcome: r for r in estimate_all(no_bmi) if r.horizon == 10}
    assert by_outcome["heart_failure"].probability is None
    assert by_outcome["heart_failure"].ineligible_reasons == ["bmi missing"]
    for outcome in ("total_cvd", "ascvd"):
        assert "bmi" not in required_inputs("male", 10, outcome)
        assert by_outcome[outcome].probability is not None


def test_unknown_sex_is_ineligible():
    res = estimate(_with(sex=None), 10, "total_cvd")
    assert res.probability is None and "sex" in res.ineligible_reasons[0]


def test_results_are_unrounded_probabilities():
    p = estimate(BASE, 10, "total_cvd").probability
    assert 0 < p < 1 and round(p, 3) != p


# Official worked examples (supplement Tables S12A and S12F): exact risks, both sexes.
WORKED = dict(age=50, total_c=200, hdl_c=45, sbp=160, diabetes=True, smoking=False, bmi=35, egfr=90,
              bp_tx=True, statin=False)
WORKED_RISK = {
    10: {"total_cvd": (0.14683939095644824, 0.16317056158151638), "ascvd": (0.09195089753632872, 0.10194362642179755),
         "heart_failure": (0.08056096777914257, 0.10591096013400046)},
    30: {"total_cvd": (0.5298503870635785, 0.5143976549039669), "ascvd": (0.3542551988690411, 0.3485940384298915),
         "heart_failure": (0.3896022671106631, 0.4235967893564546)},
}


@pytest.mark.parametrize("horizon", [10, 30])
@pytest.mark.parametrize("outcome", ["total_cvd", "ascvd", "heart_failure"])
def test_matches_official_supplement_worked_example(horizon, outcome):
    for sex, expected in zip(("female", "male"), WORKED_RISK[horizon][outcome]):
        res = estimate(PreventInputs(sex=sex, **WORKED), horizon, outcome)
        assert abs(res.probability - expected) < 1e-12, (sex, res.probability, expected)
