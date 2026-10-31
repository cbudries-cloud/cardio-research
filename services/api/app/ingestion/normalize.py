"""Normalization of test names, units, values, specimens and reference ranges.

Rules (see docs/decisions.md D-010..D-013):
- Normalization never discards the original text.
- No unit conversion. normalized_value is the reported number; normalized_unit is a
  canonical spelling of the reported unit. Results in different units form separate series.
- Unknown names, units and specimens stay unknown rather than being guessed.
"""

import re
from decimal import Decimal, InvalidOperation

# canonical key -> aliases (compared after _clean_name)
TEST_ALIASES: dict[str, tuple[str, ...]] = {
    "total_cholesterol": ("cholesterol total", "total cholesterol", "cholesterol", "tc"),
    "ldl_cholesterol": ("ldl cholesterol", "ldl c", "ldl", "ldl chol", "ldlc"),
    "hdl_cholesterol": ("hdl cholesterol", "hdl c", "hdl", "hdl chol", "hdlc"),
    "triglycerides": ("triglycerides", "triglyceride", "tg", "trig"),
    "non_hdl_cholesterol": ("non hdl cholesterol", "non hdl c", "non hdl", "nonhdl cholesterol"),
    "vldl_cholesterol": ("vldl cholesterol", "vldl c", "vldl"),
    "apolipoprotein_b": ("apolipoprotein b", "apo b", "apob", "apolipoprotein b100", "apo b100"),
    "lipoprotein_a": ("lipoprotein a", "lp a", "lpa", "lipoprotein little a"),
    "hemoglobin_a1c": ("hemoglobin a1c", "hba1c", "a1c", "glycated hemoglobin", "glycohemoglobin"),
    "glucose": ("glucose", "fasting glucose", "glucose fasting", "blood glucose"),
    "insulin": ("insulin", "fasting insulin", "insulin fasting"),
    "hs_crp": ("hs crp", "hscrp", "high sensitivity crp", "c reactive protein high sensitivity",
               "crp high sensitivity", "hs c reactive protein"),
    "creatinine": ("creatinine",),
    "egfr": ("egfr", "estimated gfr", "egfr creatinine"),
}
_ALIAS_INDEX = {alias: key for key, aliases in TEST_ALIASES.items() for alias in aliases}

# Tests that are derived from other measurements by definition.
INHERENTLY_CALCULATED = {"non_hdl_cholesterol", "egfr"}

_QUALIFIER_WORDS = {"calculated", "calc", "direct", "measured", "serum", "plasma", "blood"}

UNIT_CANONICAL = {
    "mg/dl": "mg/dL",
    "mmol/l": "mmol/L",
    "nmol/l": "nmol/L",
    "umol/l": "µmol/L",
    "µmol/l": "µmol/L",
    "mg/l": "mg/L",
    "g/dl": "g/dL",
    "g/l": "g/L",
    "%": "%",
    "mmol/mol": "mmol/mol",
    "uiu/ml": "µIU/mL",
    "µiu/ml": "µIU/mL",
    "miu/l": "mIU/L",
    "pmol/l": "pmol/L",
    "ml/min/1.73m2": "mL/min/1.73m²",
    "ml/min/1.73 m2": "mL/min/1.73m²",
    "ml/min/1.73m²": "mL/min/1.73m²",
    # Spellings only; no conversion between them.
    "ng/ml": "ng/mL",
    "ng/dl": "ng/dL",
    "pg/ml": "pg/mL",
    "mcg/dl": "µg/dL",
    "µg/dl": "µg/dL",
    "ug/dl": "µg/dL",
    "mcg/l": "µg/L",
    "µg/l": "µg/L",
    "u/l": "U/L",
    "iu/l": "IU/L",
    "iu/ml": "IU/mL",
    "miu/ml": "mIU/mL",
    "cells/ul": "cells/µL",
    "thousand/ul": "thousand/µL",
    "million/ul": "million/µL",
    "fl": "fL",
    "pg": "pg",
    "/hpf": "/HPF",
    "/lpf": "/LPF",
    "ml/min": "mL/min",
}


def _clean_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def normalize_test_name(original: str) -> tuple[str | None, str]:
    """Return (normalized key or None, value_origin)."""
    cleaned = _clean_name(original)
    words = cleaned.split()
    origin = "not_stated"
    if any(w.startswith("calc") for w in words):
        origin = "calculated"
    elif any(w in ("direct", "measured") for w in words):
        origin = "measured_direct"
    core = " ".join(w for w in words if w not in _QUALIFIER_WORDS)
    key = _ALIAS_INDEX.get(core) or _ALIAS_INDEX.get(cleaned)
    if key in INHERENTLY_CALCULATED and origin == "not_stated":
        origin = "calculated"
    return key, origin


def origin_from_method(method: str | None, current: str) -> str:
    if not method:
        return current
    m = method.lower()
    if any(k in m for k in ("calculated", "friedewald", "martin", "sampson", "derived")) or re.search(r"\bcalc\b", m):
        return "calculated"
    if "direct" in m and current == "not_stated":
        return "measured_direct"
    return current


def normalize_unit(original: str | None) -> tuple[str | None, bool]:
    """Return (canonical unit or None, recognized)."""
    if original is None or not original.strip():
        return None, False
    key = original.strip().lower()
    for candidate in (key, key.replace(" ", "")):
        if candidate in UNIT_CANONICAL:
            return UNIT_CANONICAL[candidate], True
    return original.strip(), False


_VALUE = re.compile(r"^(<=|>=|<|>)?\s*(-?\d[\d,]*(?:\.\d+)?|-?\.\d+)$")


def parse_value(raw: str | None) -> tuple[Decimal | None, str | None, str | None]:
    """Return (numeric, comparator, issue). issue is None, 'missing_value' or 'non_numeric_value'."""
    if raw is None or not raw.strip():
        return None, None, "missing_value"
    m = _VALUE.match(raw.strip())
    if not m:
        return None, None, "non_numeric_value"
    try:
        return Decimal(m[2].replace(",", "")), m[1], None
    except InvalidOperation:
        return None, None, "non_numeric_value"


# Categorical results as laboratories print them. Matched case-insensitively on the whole value.
CATEGORICAL_VALUES = {
    "negative", "positive", "neg", "pos", "none", "none seen", "not detected", "detected", "trace",
    "reactive", "non-reactive", "nonreactive", "clear", "cloudy", "hazy", "turbid", "yellow",
    "straw", "amber", "pale yellow", "dark yellow", "colorless", "normal", "abnormal", "few", "rare",
    "moderate", "many", "small", "large", "a", "b", "i", "pattern a", "pattern b", "intermediate",
}
_DIMENSIONLESS_NAME = re.compile(r"\bratio\b|\bindex\b|\bpattern\b|\bspecific gravity\b|\bph\b|/", re.I)
RESULT_TYPES = ("quantity", "dimensionless", "categorical", "bounded", "text")


def result_type(test_name: str, value_raw: str | None, numeric, comparator: str | None, unit_raw: str | None) -> str:
    """Classify a result without forcing it into number-plus-unit form.

    bounded: a number with a comparator ("<10"); the bound is never an exact value.
    dimensionless: a number with no unit whose test is a ratio, index, pH or specific gravity.
    categorical: a value from CATEGORICAL_VALUES (or "1+"..."4+").
    """
    if numeric is not None:
        if comparator:
            return "bounded"
        if unit_raw is None and _DIMENSIONLESS_NAME.search(test_name or ""):
            return "dimensionless"
        return "quantity"
    v = (value_raw or "").strip().lower()
    if v in CATEGORICAL_VALUES or re.fullmatch(r"[1-4]\+", v):
        return "categorical"
    return "text"


_RANGE_BETWEEN = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)")
_RANGE_UPPER = re.compile(r"^(?:<|<=|≤|less than)\s*(-?\d+(?:\.\d+)?)", re.I)
_RANGE_LOWER = re.compile(r"^(?:>|>=|≥|greater than)\s*(-?\d+(?:\.\d+)?)", re.I)


def parse_reference_range(raw: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Parse simple numeric bounds. The raw text remains authoritative."""
    if raw is None or not raw.strip():
        return None, None
    s = raw.strip()
    if m := _RANGE_BETWEEN.match(s):
        return Decimal(m[1]), Decimal(m[2])
    if m := _RANGE_UPPER.match(s):
        return None, Decimal(m[1])
    if m := _RANGE_LOWER.match(s):
        return Decimal(m[1]), None
    return None, None


def normalize_specimen(raw: str | None) -> tuple[str, str | None]:
    """Return (specimen_type, collection_method if stated by the specimen text)."""
    if raw is None or not raw.strip():
        return "unknown", None
    s = raw.lower()
    method = None
    if any(k in s for k in ("capillary", "finger", "dried blood spot", "dbs", "fingerstick")):
        method = "capillary"
    elif any(k in s for k in ("venous", "venipuncture", "venepuncture", "blood draw")):
        method = "venous"
    if "dried blood spot" in s or re.search(r"\bdbs\b", s):
        return "dried_blood_spot", "capillary"
    if "serum" in s:
        return "serum", method
    if "plasma" in s:
        return "plasma", method
    if "whole blood" in s:
        return "whole_blood", method
    if "urine" in s:
        return "urine", method
    return "unknown", method


def normalize_collection_method(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    s = raw.lower()
    if any(k in s for k in ("capillary", "finger", "dried blood spot", "dbs")):
        return "capillary"
    if any(k in s for k in ("venous", "venipuncture", "venepuncture", "blood draw", "phlebotomy")):
        return "venous"
    return None


def is_corrected_status(raw: str | None) -> bool:
    return bool(raw) and bool(re.search(r"\bcorrect(ed|ion)\b|\bamended\b|\brevised\b", raw.lower()))
