"""PREVENT base equations (10- and 30-year total CVD, ASCVD, heart failure).

Pure functions. No database access, no rounding, no imputation, no clamping: an input that is
missing or outside the published range makes the affected outcome ineligible, with a stated
reason. Coefficients and their provenance live in prevent_base_coefficients.json; every result
records that file's SHA-256. See docs/milestone-3-plan.md for acceptance status (3A is not
accepted until outputs match authoritative reference cases).
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

_COEF_PATH = Path(__file__).with_name("prevent_base_coefficients.json")
_COEF_BYTES = _COEF_PATH.read_bytes()
COEFFICIENTS = json.loads(_COEF_BYTES)
COEFFICIENTS_SHA256 = hashlib.sha256(_COEF_BYTES).hexdigest()
EQUATION = "PREVENT base model (Khan et al., Circulation 2024)"
OUTCOMES = ("total_cvd", "ascvd", "heart_failure")
HORIZONS = (10, 30)

# Allowable input ranges from the official supplement (Tables S12A/S12F, 2025-09-25 file linked
# from the 2026-10-14 correction). Inclusive, except BMI, whose upper bound is "<40".
AGE_RANGE = {10: (30, 79), 30: (30, 59)}
RANGES = {
    "total_c": (130, 320),  # mg/dL
    "hdl_c": (20, 100),  # mg/dL
    "sbp": (90, 200),  # mm Hg
    "egfr": (15, 150),  # mL/min/1.73m²
    "bmi": (18.5, 40),  # kg/m², upper bound exclusive
}
EXCLUSIVE_UPPER = {"bmi"}
BINARY = ("diabetes", "smoking", "bp_tx", "statin")

# Which inputs each term depends on. An outcome requires an input only if some term that uses
# it has a non-zero coefficient for that outcome.
_TERM_INPUTS = {
    "age": {"age"}, "age_squared": {"age"},
    "non_hdl_c": {"total_c", "hdl_c"}, "hdl_c": {"hdl_c"},
    "sbp_lt_110": {"sbp"}, "sbp_gte_110": {"sbp"},
    "diabetes": {"diabetes"}, "smoking": {"smoking"},
    "bmi_lt_30": {"bmi"}, "bmi_gte_30": {"bmi"},
    "egfr_lt_60": {"egfr"}, "egfr_gte_60": {"egfr"},
    "bp_tx": {"bp_tx"}, "statin": {"statin"},
    "bp_tx_sbp_gte_110": {"bp_tx", "sbp"}, "statin_non_hdl_c": {"statin", "total_c", "hdl_c"},
    "age_non_hdl_c": {"age", "total_c", "hdl_c"}, "age_hdl_c": {"age", "hdl_c"},
    "age_sbp_gte_110": {"age", "sbp"}, "age_diabetes": {"age", "diabetes"},
    "age_smoking": {"age", "smoking"}, "age_bmi_gte_30": {"age", "bmi"},
    "age_egfr_lt_60": {"age", "egfr"}, "constant": set(),
}


@dataclass(frozen=True)
class PreventInputs:
    sex: str | None  # "female" | "male"
    age: float | None  # years
    total_c: float | None = None  # mg/dL
    hdl_c: float | None = None  # mg/dL
    sbp: float | None = None  # mm Hg
    egfr: float | None = None
    bmi: float | None = None
    diabetes: bool | None = None
    smoking: bool | None = None
    bp_tx: bool | None = None
    statin: bool | None = None


@dataclass
class OutcomeResult:
    outcome: str
    horizon: int
    probability: float | None
    ineligible_reasons: list[str] = field(default_factory=list)


def required_inputs(sex: str, horizon: int, outcome: str) -> set[str]:
    coef = COEFFICIENTS["horizons"][str(horizon)]["coefficients"][sex][outcome]
    needed = {"age"}
    for term, value in coef.items():
        if value != 0:
            needed |= _TERM_INPUTS[term]
    return needed


def _terms(x: PreventInputs, horizon: int) -> dict[str, float]:
    mmol = COEFFICIENTS["chol_mg_dl_to_mmol_l"]
    age = (x.age - 55) / 10
    t: dict[str, float] = {"age": age}
    if horizon == 30:
        t["age_squared"] = age * age
    have_lipids = x.total_c is not None and x.hdl_c is not None
    non_hdl = (x.total_c - x.hdl_c) * mmol - 3.5 if have_lipids else 0.0
    hdl = (x.hdl_c * mmol - 1.3) / 0.3 if x.hdl_c is not None else 0.0
    sbp_lt = (min(x.sbp, 110) - 110) / 20 if x.sbp is not None else 0.0
    sbp_gte = (max(x.sbp, 110) - 130) / 20 if x.sbp is not None else 0.0
    bmi_lt = (min(x.bmi, 30) - 25) / 5 if x.bmi is not None else 0.0
    bmi_gte = (max(x.bmi, 30) - 30) / 5 if x.bmi is not None else 0.0
    egfr_lt = (min(x.egfr, 60) - 60) / -15 if x.egfr is not None else 0.0
    egfr_gte = (max(x.egfr, 60) - 90) / -15 if x.egfr is not None else 0.0
    dm, smk, bptx, stat = (float(bool(v)) for v in (x.diabetes, x.smoking, x.bp_tx, x.statin))
    t.update({
        "non_hdl_c": non_hdl, "hdl_c": hdl, "sbp_lt_110": sbp_lt, "sbp_gte_110": sbp_gte,
        "diabetes": dm, "smoking": smk, "bmi_lt_30": bmi_lt, "bmi_gte_30": bmi_gte,
        "egfr_lt_60": egfr_lt, "egfr_gte_60": egfr_gte, "bp_tx": bptx, "statin": stat,
        "bp_tx_sbp_gte_110": bptx * sbp_gte, "statin_non_hdl_c": stat * non_hdl,
        "age_non_hdl_c": age * non_hdl, "age_hdl_c": age * hdl, "age_sbp_gte_110": age * sbp_gte,
        "age_diabetes": age * dm, "age_smoking": age * smk, "age_bmi_gte_30": age * bmi_gte,
        "age_egfr_lt_60": age * egfr_lt, "constant": 1.0,
    })
    return t


def _in_range(name: str, value: float) -> bool:
    lo, hi = RANGES[name]
    return lo <= value < hi if name in EXCLUSIVE_UPPER else lo <= value <= hi


def _ineligible(x: PreventInputs, horizon: int, needed: set[str]) -> list[str]:
    reasons = []
    if x.sex not in ("female", "male"):
        return ["sex missing or not female/male (the equations are sex-specific)"]
    lo, hi = AGE_RANGE[horizon]
    if x.age is None:
        reasons.append("age missing")
    elif not lo <= x.age <= hi:
        reasons.append(f"age {x.age:g} outside {lo}-{hi} for the {horizon}-year equations")
    for name in sorted(needed - {"age"}):
        value = getattr(x, name)
        if value is None:
            reasons.append(f"{name} missing")
        elif name in RANGES and not _in_range(name, value):
            lo_, hi_ = RANGES[name]
            upper = f"<{hi_:g}" if name in EXCLUSIVE_UPPER else f"{hi_:g}"
            reasons.append(f"{name} {value:g} outside published range {lo_:g} to {upper}")
    if "total_c" in needed and x.total_c is not None and x.hdl_c is not None and x.hdl_c >= x.total_c:
        reasons.append("HDL-C is not below total cholesterol")
    return reasons


def estimate(x: PreventInputs, horizon: int, outcome: str) -> OutcomeResult:
    if horizon not in HORIZONS or outcome not in OUTCOMES:
        raise ValueError(f"unsupported horizon/outcome {horizon}/{outcome}")
    sex = x.sex if x.sex in ("female", "male") else "female"
    reasons = _ineligible(x, horizon, required_inputs(sex, horizon, outcome))
    if reasons:
        return OutcomeResult(outcome, horizon, None, reasons)
    coef = COEFFICIENTS["horizons"][str(horizon)]["coefficients"][x.sex][outcome]
    terms = _terms(x, horizon)
    log_odds = math.fsum(coef[k] * terms[k] for k in coef)
    return OutcomeResult(outcome, horizon, 1 / (1 + math.exp(-log_odds)))


def estimate_all(x: PreventInputs) -> list[OutcomeResult]:
    return [estimate(x, h, o) for h in HORIZONS for o in OUTCOMES]
