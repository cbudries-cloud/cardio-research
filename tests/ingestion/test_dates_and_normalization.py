from datetime import date
from decimal import Decimal

import pytest

from app.ingestion.dates import parse_date
from app.ingestion.normalize import (
    normalize_specimen,
    normalize_test_name,
    normalize_unit,
    parse_reference_range,
    parse_value,
)


@pytest.mark.parametrize(
    "raw, order, expected, status",
    [
        ("2023-03-04", None, date(2023, 3, 4), "exact"),
        ("2023/03/04", None, date(2023, 3, 4), "exact"),
        ("Mar 4, 2023", None, date(2023, 3, 4), "exact"),
        ("4 March 2023", None, date(2023, 3, 4), "exact"),
        ("03/14/2023", None, date(2023, 3, 14), "exact"),  # 14 cannot be a month
        ("14/03/2023", None, date(2023, 3, 14), "exact"),
        ("05/05/2023", None, date(2023, 5, 5), "exact"),  # both orders agree
        ("03/04/2023", None, None, "ambiguous"),
        ("03/04/2023", "MDY", date(2023, 3, 4), "exact"),
        ("03/04/2023", "DMY", date(2023, 4, 3), "exact"),
        ("06/04/24", "MDY", None, "ambiguous"),  # two-digit year stays ambiguous
        ("", None, None, "missing"),
        (None, None, None, "missing"),
        ("2023-02-30", None, None, "unparseable"),
        ("sometime in spring", None, None, "unparseable"),
    ],
)
def test_parse_date_never_guesses(raw, order, expected, status):
    parsed = parse_date(raw, order)
    assert parsed.value == expected
    assert parsed.status == status


def test_declared_order_is_recorded_as_interpretation():
    assert parse_date("03/04/2023", "MDY").interpretation == "declared_order_MDY"


@pytest.mark.parametrize(
    "name, key, origin",
    [
        ("LDL Cholesterol (calculated)", "ldl_cholesterol", "calculated"),
        ("LDL-C", "ldl_cholesterol", "not_stated"),
        ("LDL Cholesterol, Direct", "ldl_cholesterol", "measured_direct"),
        ("Non-HDL Cholesterol", "non_hdl_cholesterol", "calculated"),
        ("Lp(a)", "lipoprotein_a", "not_stated"),
        ("Lipoprotein (a)", "lipoprotein_a", "not_stated"),
        ("ApoB", "apolipoprotein_b", "not_stated"),
        ("Analyte X-17", None, "not_stated"),
    ],
)
def test_test_name_normalization(name, key, origin):
    assert normalize_test_name(name) == (key, origin)


def test_units_are_canonicalized_not_converted():
    assert normalize_unit("mg/dl") == ("mg/dL", True)
    assert normalize_unit("nmol/L") == ("nmol/L", True)
    assert normalize_unit("U/L") == ("U/L", True)
    assert normalize_unit("EU/dL") == ("EU/dL", False)  # unknown spelling stays as written
    assert normalize_unit("") == (None, False)
    assert normalize_unit(None) == (None, False)


def test_value_parsing():
    assert parse_value("212") == (Decimal("212"), None, None)
    assert parse_value("1,234.5") == (Decimal("1234.5"), None, None)
    assert parse_value("<0.3") == (Decimal("0.3"), "<", None)
    assert parse_value("See note") == (None, None, "non_numeric_value")
    assert parse_value("") == (None, None, "missing_value")


def test_reference_range_parsing_keeps_unknown_shapes_unparsed():
    assert parse_reference_range("40-60") == (Decimal(40), Decimal(60))
    assert parse_reference_range("<200") == (None, Decimal(200))
    assert parse_reference_range(">39") == (Decimal(39), None)
    assert parse_reference_range("Desirable: see comment") == (None, None)


def test_specimen_normalization_keeps_unknown_unknown():
    assert normalize_specimen("Dried blood spot") == ("dried_blood_spot", "capillary")
    assert normalize_specimen("Serum") == ("serum", None)  # serum alone does not prove venous
    assert normalize_specimen("Specimen B") == ("unknown", None)
    assert normalize_specimen(None) == ("unknown", None)
