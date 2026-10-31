"""Milestone 3A criterion 1: outputs match the AHA PREVENT online calculator.

Reference values are as displayed (one decimal place, in percent). A match means the engine's
probability, in percent, is within half a display unit of the displayed value."""

import json
from pathlib import Path

import pytest

from app.risk.prevent import PreventInputs, estimate

DOC = json.loads((Path(__file__).parent / "data" / "aha_calculator_reference_cases.json").read_text())
CASES = [(c["id"], o, h, c) for c in DOC["cases"] for o in ("total_cvd", "ascvd", "heart_failure") for h in (10, 30)]


def test_reference_set_covers_the_planned_conditions():
    cases = DOC["cases"]
    assert len(cases) >= 12
    assert {c["inputs"]["sex"] for c in cases} == {"female", "male"}
    assert {30, 59, 60, 79} <= {c["inputs"]["age"] for c in cases}
    for flag in ("diabetes", "smoking", "statin", "bp_tx"):
        assert {c["inputs"][flag] for c in cases} == {True, False}


@pytest.mark.parametrize("case_id,outcome,horizon,case", CASES, ids=[f"{c[0]}-{c[1]}-{c[2]}y" for c in CASES])
def test_matches_aha_calculator(case_id, outcome, horizon, case):
    expected = case["expected_percent"][outcome][str(horizon)]
    res = estimate(PreventInputs(**case["inputs"]), horizon, outcome)
    if expected is None:
        assert res.probability is None, "calculator shows no estimate; engine must not either"
        return
    assert res.probability is not None, res.ineligible_reasons
    assert abs(res.probability * 100 - expected) <= 0.05 + 1e-9, (res.probability * 100, expected)
