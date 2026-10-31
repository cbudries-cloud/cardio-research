"""Research workflow v0.2 on synthetic records: evidence dependency, provider labelling,
verified vs provisional inputs, clinician queue, and the corrected prediction window."""

from datetime import date
from pathlib import Path

import pytest

from conftest import accept, by_test, observations_for, upload

from app.research import discrepancy, providers, readers, retrieval, runtime

HEADER = b"Test,Result,Units,Collection Date,Lab,Reference Range,Flag,Method\n"
DRAW = (b"LDL PARTICLE NUMBER,1500,nmol/L,2025-01-10,SYA,<1138,H,Ion Mobility\n"
        b"Apolipoprotein B,66,mg/dL,2025-01-10,SYB,<90,,\n"
        b"LDL Cholesterol (direct),80,mg/dL,2025-01-10,SYA,<100,,\n"
        b"LDL SMALL,240,nmol/L,2025-01-10,SYA,<142,H,Ion Mobility\n"
        b"Hemoglobin A1c,5.3,%,2025-01-10,SYB,<5.7,,\n")


def _setup(client, extra: bytes = b""):
    doc = upload(client, "draw.csv", data=HEADER + DRAW + extra)
    assert client.post(f"/api/v1/documents/{doc['id']}/auto-accept").status_code == 200
    return doc


def _snap(client):
    r = client.post("/api/v1/research/snapshots")
    assert r.status_code == 201, r.text
    return r.json()


def _preview(snap):
    return snap["outputs"]["research_v02"]["provisional_preview"]


def _claim(research, prefix):
    return next((c for c in research["claims"] if c["id"].startswith(prefix)), None)


def test_three_questions_are_answered_separately_with_sources(client):
    _setup(client)
    r = _preview(_snap(client))
    roles = {x["role"]: x for x in r["q1_extraction"]}
    assert roles["LDL particle number"]["method"] == "ion_mobility"
    assert roles["ApoB"]["method"] == "not_stated_in_report"  # never inferred from the laboratory code
    assert "measured on 1 date" in r["q2_reproducibility_and_interpretability"][0]
    count = _claim(r, "apob-particle-count")
    assert "1200 nmol/L" in count["text"] and "1.25 times" in count["text"]  # 66 mg/dL x 1e4/550
    assert "1289 nmol/L" in count["text"] and "1.16 times" in count["text"]  # 66 mg/dL / 0.0512
    assert "not consistent with each other on a common scale" in count["text"]
    assert discrepancy.CHECK_USE in count["text"] and "units: ApoB mg/dL" in count["text"]
    check = r["consistency_checks"][0]
    assert check["outcome"] == "ldlp_exceeds_apob_count_under_all_assumptions" and check["use"] == discrepancy.CHECK_USE
    assert len(check["assumptions"]) == 2 and any("ApoB assay" in x for x in check["limitations"])
    assert r["q3_clinical_interpretation"] and "establish a personal risk" in r["q3_clinical_interpretation"][1]
    small = next(h for h in r["hypotheses"] if h["hypothesis"].startswith("More small"))
    assert any("would not put LDL-P above" in c and "common scale" in c for c in small["contrary"])


def test_removing_a_supporting_observation_withdraws_dependent_claims(client):
    doc = _setup(client)
    first = _preview(_snap(client))
    apob = by_test(observations_for(client, doc["id"]), "apolipoprotein_b")[0]
    assert client.post(f"/api/v1/observations/{apob['id']}/reject", json={"reason": "test"}).status_code == 200
    snap = _snap(client)
    second = _preview(snap)
    withdrawn = snap["outputs"]["diff_from_previous"]["provisional_preview"]["withdrawn"]
    for c in first["claims"]:
        if apob["id"] in c["depends_on_observations"]:
            assert c["id"] in withdrawn and _claim(second, c["id"]) is None
    assert _claim(second, "ldlp-measurement-count") is not None  # does not depend on ApoB


def test_correcting_an_observation_updates_dependent_claims(client):
    doc = _setup(client)
    _snap(client)
    apob = by_test(observations_for(client, doc["id"]), "apolipoprotein_b")[0]
    r = client.post(f"/api/v1/observations/{apob['id']}/correct", json={"reason": "misread", "value": "88"})
    assert r.status_code == 201, r.text
    assert accept(client, r.json()["id"]).status_code == 200
    snap = _snap(client)
    count = _claim(_preview(snap), "apob-particle-count")
    assert "ApoB 88 mg/dL" in count["text"] and "as expected" in count["text"]  # 88 -> 1600 and 1719 nmol/L >= 1500
    assert count["id"] in snap["outputs"]["diff_from_previous"]["provisional_preview"]["changed"]


def test_removing_an_unrelated_observation_changes_no_claim(client):
    doc = _setup(client)
    _snap(client)
    a1c = by_test(observations_for(client, doc["id"]), "hemoglobin_a1c")[0]
    client.post(f"/api/v1/observations/{a1c['id']}/reject", json={"reason": "test"})
    d = _snap(client)["outputs"]["diff_from_previous"]["provisional_preview"]
    assert d["withdrawn"] == [] and d["changed"] == [] and d["added"] == [] and d["unchanged"]


def test_unavailable_evidence_produces_an_explicit_limitation(client):
    _setup(client)
    inputs_snap = _snap(client)["inputs"]
    full = runtime.load_ledger(Path("/research"))
    ledger = {k: v for k, v in full.items() if k != "glavinovic-2022-apob-physiology"}
    r = discrepancy.investigate_discrepancy(inputs_snap["observations"], ledger, {}, env={})
    assert any("glavinovic-2022-apob-physiology" in lim for lim in r["limitations"])
    assert [a["label"] for a in r["consistency_checks"][0]["assumptions"]] == ["0.0512 mg/dL per nmol/L (authors' factor)"]
    ledger = {k: v for k, v in ledger.items() if k != "epstein-2025-apob-vs-ldlp"}
    r = discrepancy.investigate_discrepancy(inputs_snap["observations"], ledger, {}, env={})
    assert _claim(r, "apob-particle-count") is None and r["consistency_checks"] == []
    assert any("consistency check not made" in lim for lim in r["limitations"])


def test_bounded_values_are_never_converted_as_exact(client):
    upload(client, "b.csv", data=HEADER + b"LDL PARTICLE NUMBER,1500,nmol/L,2025-01-10,SYA,<1138,H,Ion Mobility\n"
           b"Apolipoprotein B,<20,mg/dL,2025-01-10,SYB,<90,,\n")
    for d in client.get("/api/v1/documents").json():
        client.post(f"/api/v1/documents/{d['id']}/auto-accept")
    r = _preview(_snap(client))
    assert _claim(r, "apob-particle-count") is None
    assert any("bounded" in lim for lim in r["limitations"])


def test_verified_analysis_uses_only_participant_confirmed_observations(client):
    doc = _setup(client)
    snap = _snap(client)
    assert snap["outputs"]["research_v02"]["verified"] is None  # nothing confirmed yet
    assert snap["outputs"]["inputs_split"] == {"verified": 0, "provisional": 5}
    for name in ("LDL PARTICLE NUMBER",):
        o = next(o for o in observations_for(client, doc["id"]) if o["original_test_name"] == name)
        client.post(f"/api/v1/observations/{o['id']}/confirm", json={"confirm_source_matches": True})
    verified = _snap(client)["outputs"]["research_v02"]["verified"]
    assert verified is not None and _claim(verified, "apob-particle-count") is None  # ApoB not confirmed: no pair


def test_snapshots_never_call_a_live_model(client, monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("sk-test")
    monkeypatch.setenv("CARDIO_LLM_API_KEY_FILE", str(key))
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-opus-5-5")
    monkeypatch.setattr(providers.AnthropicProvider, "send", lambda *a, **k: pytest.fail("snapshot called a model"))
    _setup(client)
    r = _preview(_snap(client))
    assert r["interpretation"]["execution"] == "mock" and r["interpretation"]["text"].startswith("[MOCK")


def test_live_provider_reports_missing_key_file_and_model():
    p = providers.AnthropicProvider(env={"CARDIO_LLM_API_KEY_FILE": "/nonexistent/key"})
    b = p.blockers()
    assert any("key file /nonexistent/key" in x for x in b) and any("CARDIO_LLM_MODEL" in x for x in b)


def test_public_search_is_off_by_default_and_queries_are_non_identifying():
    out = retrieval.retrieve({}, [], list(retrieval.QUERIES), env={})
    assert all(v["status"] == "not_run" for v in out.search.values()) and out.blockers
    for q in retrieval.QUERIES.values():
        assert not any(ch.isdigit() for ch in q)


def test_reader_comparison_reports_agreement_errors_abstentions_latency_and_cost(client):
    _setup(client)
    obs = _snap(client)["inputs"]["observations"]

    class Partial:
        name = "candidate-partial"

        def read(self, observations, targets):
            res = readers.DeterministicRecordReader().read(observations, targets)
            res.found["apob"] = []
            res.abstained = ["apob"]
            res.cost_usd = 0.01
            return res

    class Broken:
        name = "candidate-broken"

        def read(self, observations, targets):
            raise RuntimeError("x")

    rep = readers.compare_readers(readers.DeterministicRecordReader(), Partial(), obs, discrepancy.TARGETS)
    assert rep["agreement"] == rep["of"] - 1 and rep["abstentions"]["candidate"] == ["apob"]
    assert rep["cost_usd"]["candidate"] == 0.01 and "latency_ms" in rep
    broken = readers.compare_readers(readers.DeterministicRecordReader(), Broken(), obs, discrepancy.TARGETS)
    assert broken["errors"]["candidate"] == ["RuntimeError"]


def test_clinician_queue_groups_iron_results_with_related_measurements(client):
    _setup(client, b'"IRON, TOTAL",209,mcg/dL,2025-01-10,SYB,50-195,H,\n'
                   b"% SATURATION,65,%,2025-01-10,SYB,20-48,H,\n"
                   b"FERRITIN,120,ng/mL,2025-01-10,SYB,38-380,,\n")
    q = _snap(client)["outputs"]["clinician_review_queue"]
    iron = next(g for g in q if g["group"] == "Iron studies")
    assert {i["test_as_written"] for i in iron["items"]} == {"IRON, TOTAL", "% SATURATION", "FERRITIN"}
    assert {i["test_as_written"]: i["outside_lab_range"] for i in iron["items"]}["FERRITIN"] is False
    assert all(i["source_status"] == "automated_check" for i in iron["items"])
    assert "does not diagnose" in iron["note"] and "self-treatment" in iron["note"]


def test_prediction_targets_a_window_after_the_snapshot_date(client):
    _setup(client)
    q = _snap(client)["outputs"]["prediction_question"]
    assert date.today().isoformat() in q["window"] and "not prospective" in q["window"]
    assert any("personal response model" in r for r in q["no_forecast_because"])


def test_biological_findings_are_separated_from_coverage_and_readiness(client):
    _setup(client)
    out = _snap(client)["outputs"]
    assert "reference-risk-not-computable" not in out["biological_findings"]
    assert any("Readiness issue" in r for r in out["readiness_issues"])
    assert all("biological" not in c or "not a biological finding" in c for c in out["coverage_limitations"])


def test_snapshot_handles_several_unit_less_series(client):
    _setup(client, b"Urine Glucose,NEGATIVE,,2025-01-10,SYB,NEGATIVE,,\n"
                   b"Urine Ketones,NEGATIVE,,2025-01-10,SYB,NEGATIVE,,\n"
                   b"Albumin/Globulin Ratio,1.8,,2025-01-10,SYB,1.0-2.5,,\n")
    snap = _snap(client)
    conv = snap["outputs"]["rules_baseline_v01"]["conventional"]
    assert {c["unit"] for c in conv} >= {None}


def test_hypotheses_keep_unknowns_symmetric_and_track_verification(client):
    doc = _setup(client)
    r = _preview(_snap(client))
    h = {x["hypothesis"].split(":")[0].split(" in ")[0]: x for x in r["hypotheses"]}
    scale = h["Cross-assay scale difference"]
    assert "immunoassay" not in scale["hypothesis"] and "method not identified" in scale["hypothesis"]
    assert scale["contrary"] == [] and any("not evidence against" in g for g in scale["evidence_gaps"])
    variation = next(x for x in r["hypotheses"] if x["hypothesis"].startswith("Analytical"))
    assert "either single measurement" in variation["hypothesis"] and len(variation["depends_on_observations"]) == 2
    assert not any("caulfield" in x for x in variation["supporting"])  # subfraction CV does not transfer to total LDL-P
    extraction = next(x for x in r["hypotheses"] if x["hypothesis"].startswith("Extraction"))
    assert extraction["supporting"] == ["Values not yet confirmed by the participant"]
    for o in observations_for(client, doc["id"]):
        client.post(f"/api/v1/observations/{o['id']}/confirm", json={"confirm_source_matches": True})
    verified = _snap(client)["outputs"]["research_v02"]["verified"]
    extraction = next(x for x in verified["hypotheses"] if x["hypothesis"].startswith("Extraction"))
    assert extraction["supporting"] == [] and extraction["distinguishing"] == []
    assert any("confirmed every value" in c for c in extraction["contrary"])


def test_epstein_rule_keeps_comparisons_distinct_and_reports_the_coefficient(client):
    _setup(client)
    rule = _claim(_preview(_snap(client)), "risk-interpretation-epstein")
    assert "0.001168" in rule["text"] and "not reported numerically" not in rule["text"]
    assert "pattern the study examined" not in rule["text"]
    assert "different comparison" in rule["text"] and "concordant control group" in rule["text"]
    assert "epstein-2025-apob-vs-ldlp/concordance-line-coefficient" in rule["depends_on_evidence"]
    count = _claim(_preview(_snap(client)), "apob-particle-count")
    assert "glavinovic-2022-apob-physiology/apob-per-ldl" in count["depends_on_evidence"]
