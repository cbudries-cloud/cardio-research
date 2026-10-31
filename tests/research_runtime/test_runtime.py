"""Research runtime v0.1 on synthetic reports: snapshot contents, rules, and limits."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from conftest import TEST_DB, observations_for, upload


def _baseline(client):
    upload(client, "note.csv", data=b"Test,Result,Units,Collection Date\nVitamin D 25-OH,SEE NOTE,ng/mL,2025-03-04\n")
    doc = upload(client, "synthetic_range_split_with_previous.pdf", date_order="MDY")
    assert client.post(f"/api/v1/documents/{doc['id']}/auto-accept").status_code == 200
    r = client.post("/api/v1/research/snapshots")
    assert r.status_code == 201, r.text
    return doc, r.json()


def test_snapshot_uses_only_boundary_observations_and_labels_confirmation(client):
    doc, snap = _baseline(client)
    rows = snap["inputs"]["observations"]
    assert rows and all(r["verification_method"] == "automated_check" for r in rows)
    assert any(r["value_as_written"] == "NEGATIVE" and r["result_type"] == "categorical" for r in rows)
    assert snap["inputs"]["excluded"]["unverified"] >= 1
    assert {r["reported_as"] for r in rows} == {"current", "historical_in_later_report"}
    for f in snap["outputs"]["rules_baseline_v01"]["findings"]:
        if f["observations"]:
            assert f["provisional"] is True  # nothing confirmed by the participant yet
    assert snap["outputs"]["rules_baseline_v01"]["verification_items"]


def test_at_most_five_findings_each_fully_specified(client):
    _, snap = _baseline(client)
    findings = snap["outputs"]["rules_baseline_v01"]["findings"]
    assert 1 <= len(findings) <= 5
    for f in findings:
        for field in ("establishes", "does_not_establish", "evidence", "distinguishing_information",
                      "decision_it_could_change", "observations"):
            assert field in f
        for o in f["observations"]:
            assert o["source"]["document_id"] and o["source"]["page"] and o["collection_date"] and "unit" in o


def test_lipid_history_includes_reprinted_previous_results_without_reconstruction(client):
    _, snap = _baseline(client)
    f = next(f for f in snap["outputs"]["rules_baseline_v01"]["findings"] if f["id"] == "atherogenic-lipoprotein-history")
    dates = {o["collection_date"] for o in f["observations"]}
    assert {"2024-02-10", "2025-03-04"} <= dates
    assert any("not reconstructed" in s for s in f["does_not_establish"])
    assert any("previous results reprinted" in c for c in f["comparability"])


def test_apob_ldl_comparison_uses_only_quoted_interval(client):
    _, snap = _baseline(client)
    f = next(f for f in snap["outputs"]["rules_baseline_v01"]["findings"] if f["id"] == "apob-ldl-concordance")
    # Synthetic: LDL-C 134, apoB 108 on 2025-03-04; quoted interval at LDL-C 130 is 85.8-108.8.
    assert any("85.8-108.8" in e and "within that interval, 0.8 mg/dL from its nearest bound" in e
               for e in f["establishes"])
    ev = f["evidence"][0]
    assert ev["available"] and "apob-range-ldl130" in {c["id"] for c in ev["claims"]}
    assert any("not personal risk" in s for s in f["does_not_establish"])


def test_prediction_question_has_no_numerical_forecast(client):
    _, snap = _baseline(client)
    q = snap["outputs"]["rules_baseline_v01"]["prediction_question"]
    assert q["comparison_baselines"] and q["no_forecast_because"]
    assert not any(k in q for k in ("forecast", "predicted_value", "interval"))


def test_reference_risk_is_reported_as_not_computable(client):
    _, snap = _baseline(client)
    f = next(f for f in snap["outputs"]["rules_baseline_v01"]["findings"] if f["id"] == "reference-risk-not-computable")
    assert "systolic blood pressure" in " ".join(f["establishes"])


def test_snapshots_are_versioned_and_append_only(client):
    _, first = _baseline(client)
    second = client.post("/api/v1/research/snapshots").json()
    assert (first["version"], second["version"]) == (1, 2)
    assert client.get("/api/v1/research/snapshots/1").json()["outputs"] == first["outputs"]
    assert first["runtime_version"] == "0.2"
    engine = create_engine(TEST_DB)
    with pytest.raises(DBAPIError, match="not permitted"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE research_snapshots SET outputs = '{}'::jsonb"))
    engine.dispose()


def test_ldl_not_near_a_quoted_anchor_is_left_unresolved(client):
    data = (b"Test,Result,Units,Collection Date,Lab\n"
            b"LDL Cholesterol (direct),79,mg/dL,2025-01-10,SY1\nApolipoprotein B,68,mg/dL,2025-01-10,SY1\n")
    doc = upload(client, "pair.csv", data=data)
    client.post(f"/api/v1/documents/{doc['id']}/auto-accept")
    snap = client.post("/api/v1/research/snapshots").json()
    f = next(f for f in snap["outputs"]["rules_baseline_v01"]["findings"] if f["id"] == "apob-ldl-concordance")
    assert f["kind"] == "unresolved_question"
    assert "cannot be judged" in f["establishes"][0]
    assert not any("above that interval" in e for e in f["establishes"])


def test_within_range_lipids_get_a_conventional_interpretation(client):
    data = (b"Test,Result,Units,Collection Date,Lab,Reference Range\n"
            b"Apolipoprotein B,70,mg/dL,2025-01-10,SY1,<90\nApolipoprotein B,72,mg/dL,2025-07-10,SY1,<90\n")
    doc = upload(client, "within.csv", data=data)
    client.post(f"/api/v1/documents/{doc['id']}/auto-accept")
    snap = client.post("/api/v1/research/snapshots").json()
    f = next(f for f in snap["outputs"]["rules_baseline_v01"]["findings"] if f["id"] == "atherogenic-lipoprotein-history")
    assert f["interpretation"].startswith("Conventional interpretation")


def test_particle_number_conflicting_with_apob_is_raised_as_a_question(client):
    data = (b"Test,Result,Units,Collection Date,Lab,Reference Range,Flag\n"
            b"LDL PARTICLE NUMBER,1500,nmol/L,2025-01-10,SYA,<1138,H\n"
            b"Apolipoprotein B,66,mg/dL,2025-01-10,SYB,<90,\n"
            b"LDL SMALL,240,nmol/L,2025-01-10,SYA,<142,H\n")
    doc = upload(client, "particles.csv", data=data)
    client.post(f"/api/v1/documents/{doc['id']}/auto-accept")
    snap = client.post("/api/v1/research/snapshots").json()
    f = snap["outputs"]["rules_baseline_v01"]["findings"][0]
    assert f["id"] == "particle-number-vs-apob" and f["kind"] == "unresolved_question"
    text = " ".join(f["establishes"])
    assert "opposite sides of their own laboratory ranges" in text
    assert "different performing-laboratory codes" in text
    assert "measured on one date only" in text
    assert any("No conversion" in s for s in f["does_not_establish"])
