"""Specimen provenance and rule SPEC-1 (decision D-024)."""

from conftest import accept, by_test, calc_inputs, observations_for, upload


def _hba1c_from_pdf(client):
    doc = upload(client, "synthetic_lab_report_2024.pdf")
    return doc, by_test(observations_for(client, doc["id"]), "hemoglobin_a1c")[0]


def test_hba1c_under_serum_header_is_a_surfaced_conflict_not_rewritten(client):
    """Regression: the report header says 'Specimen: Serum' above a mixed panel that includes HbA1c."""
    _, hba1c = _hba1c_from_pdf(client)
    # The stated value is kept verbatim and not rewritten to the expected matrix.
    assert hba1c["specimen_type_raw"] == "Serum"
    assert hba1c["specimen_type"] == "serum"
    # It is marked as inherited, with the original header text preserved.
    assert hba1c["specimen_source"] == "report_header"
    assert hba1c["inherited_metadata"]["specimen"] == {"text": "Specimen: Serum", "page": 1}
    assert "specimen_inherited_from_report_header" in hba1c["extraction_issues"]
    # The inconsistency is surfaced by rule SPEC-1 and blocks acceptance.
    assert "specimen_conflict" in hba1c["blocking_issues"]
    r = accept(client, hba1c["id"])
    assert r.status_code == 409 and "specimen_conflict" in r.json()["info"]["blocking_issues"]
    assert calc_inputs(client, "hemoglobin_a1c") == []


def test_lipids_under_the_same_header_are_inherited_but_not_conflicting(client):
    doc, _ = _hba1c_from_pdf(client)
    ldl = by_test(observations_for(client, doc["id"]), "ldl_cholesterol")[0]
    assert ldl["specimen_source"] == "report_header"
    assert "specimen_conflict" not in ldl["extraction_issues"]
    assert ldl["blocking_issues"] == []


def test_conflict_resolved_as_unknown_stays_unknown(client):
    _, hba1c = _hba1c_from_pdf(client)
    new = client.post(f"/api/v1/observations/{hba1c['id']}/correct", json={
        "specimen_type": "unknown", "reason": "Header specimen does not apply to this row; matrix not stated"}).json()
    assert new["specimen_type"] == "unknown"
    assert new["specimen_type_raw"] == "Serum"  # original text still preserved
    assert "specimen_conflict" not in new["extraction_issues"]
    assert "unknown_specimen_type" in new["extraction_issues"]
    assert accept(client, new["id"]).status_code == 200


def test_conflict_resolved_by_participant_choice_is_audited(client):
    _, hba1c = _hba1c_from_pdf(client)
    new = client.post(f"/api/v1/observations/{hba1c['id']}/correct", json={
        "specimen_type": "whole_blood", "reason": "Lab test catalog lists EDTA whole blood for HbA1c"}).json()
    assert new["specimen_source"] == "participant_entered"
    assert new["blocking_issues"] == []
    audit = client.get(f"/api/v1/observations/{new['id']}").json()["audit"]
    corrected = next(a for a in audit if a["action"] == "observation.corrected")
    assert corrected["detail"]["before"]["specimen_type"] == "serum"
    assert corrected["detail"]["after"]["specimen_type"] == "whole_blood"
    # A later unrelated correction keeps the participant's specimen decision.
    later = client.post(f"/api/v1/observations/{new['id']}/correct", json={"flag": "N", "reason": "flag"}).json()
    assert later["specimen_type"] == "whole_blood" and later["specimen_source"] == "participant_entered"


def test_unrelated_correction_does_not_clear_conflict(client):
    _, hba1c = _hba1c_from_pdf(client)
    new = client.post(f"/api/v1/observations/{hba1c['id']}/correct", json={"flag": "N", "reason": "x"}).json()
    assert "specimen_conflict" in new["blocking_issues"]
    assert new["specimen_source"] == "report_header"


def test_row_level_specimen_is_marked_as_row(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hba1c = by_test(observations_for(client, doc["id"]), "hemoglobin_a1c")[0]
    assert hba1c["specimen_type"] == "whole_blood" and hba1c["specimen_source"] == "row"
    assert hba1c["inherited_metadata"] == {}
    assert hba1c["blocking_issues"] == []


def test_row_level_inconsistent_specimen_is_also_a_conflict(client):
    csv = b"Test,Result,Units,Collection Date,Specimen\nHemoglobin A1c,5.6,%,2024-03-01,Serum\n"
    doc = upload(client, "row_conflict.csv", data=csv)
    (obs,) = observations_for(client, doc["id"])
    assert obs["specimen_source"] == "row"
    assert "specimen_conflict" in obs["blocking_issues"]


def test_collection_method_is_not_a_substitute_for_specimen_matrix(client):
    csv = b"Test,Result,Units,Collection Date,Collection Method,Specimen\nLDL-C,120,mg/dL,2024-03-01,Venipuncture,\n"
    doc = upload(client, "method_only.csv", data=csv)
    (obs,) = observations_for(client, doc["id"])
    assert obs["collection_method"] == "venous"
    assert obs["specimen_type"] == "unknown"  # venipuncture does not establish serum vs plasma
    assert obs["specimen_source"] == "none"
    assert "unknown_specimen_type" in obs["extraction_issues"]


def test_boundary_excludes_blocking_issues_even_if_status_were_accepted(client):
    """Defense in depth: an accepted row with a blocking issue never reaches calculation inputs."""
    from sqlalchemy import create_engine, text

    from conftest import TEST_DB

    _, hba1c = _hba1c_from_pdf(client)
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:  # simulate a bypass of the application rules
        conn.execute(text("UPDATE observations SET verification_status='accepted', verified_at=now() "
                          "WHERE id=:id"), {"id": hba1c["id"]})
    engine.dispose()
    assert calc_inputs(client, "hemoglobin_a1c") == []
