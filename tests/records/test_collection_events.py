"""Corrected results and duplicate candidates use collection-event context, not value alone."""

from sqlalchemy import create_engine, text

from conftest import TEST_DB, accept, by_test, calc_inputs, observations_for, upload

HEADER = b"Test,Result,Units,Collection Date,Lab,Accession,Result Status\n"


def _flags(client):
    return client.get("/api/v1/flags").json()


def test_same_day_repeat_with_different_accession_is_not_flagged(client):
    upload(client, "a.csv", data=HEADER + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,ACC-1,Final\n")
    upload(client, "b.csv", data=HEADER + b"LDL-C,112,mg/dL,2024-02-01,SYN Lab,ACC-2,Final\n")
    assert _flags(client) == []  # legitimate repeated test; nothing merged, nothing flagged


def test_corrected_value_with_same_accession_is_flagged_as_possible_replacement(client):
    upload(client, "orig.csv", data=HEADER + b"LDL-C,131,mg/dL,2024-01-15,SYN Lab,ACC-9,Final\n")
    upload(client, "corr.csv", data=HEADER + b"LDL-C,127,mg/dL,2024-01-15,SYN Lab,ACC-9,Corrected\n")
    (flag,) = _flags(client)
    assert flag["kind"] == "possible_lab_correction"
    assert flag["detail"]["match_basis"] == "same_accession"
    assert flag["detail"]["accession_new"] == flag["detail"]["accession_existing"] == "ACC-9"


def test_corrected_report_for_a_different_accession_is_not_proposed_as_replacement(client):
    upload(client, "orig.csv", data=HEADER + b"LDL-C,131,mg/dL,2024-01-15,SYN Lab,ACC-9,Final\n")
    upload(client, "corr.csv", data=HEADER + b"LDL-C,127,mg/dL,2024-01-15,SYN Lab,ACC-10,Corrected\n")
    assert _flags(client) == []


def test_without_identifiers_a_weak_match_is_flagged_for_review_only(client):
    h = b"Test,Result,Units,Collection Date\n"
    upload(client, "a.csv", data=h + b"LDL-C,120,mg/dL,2024-02-01\n")
    upload(client, "b.csv", data=h + b"LDL-C,112,mg/dL,2024-02-01\n")
    (flag,) = _flags(client)
    assert flag["kind"] == "conflicting_value"
    assert flag["detail"]["match_basis"] == "date_and_test_only"
    # Not merged: both observations still exist and are unverified.
    obs = client.get("/api/v1/observations").json()
    assert sorted(o["original_value"] for o in obs) == ["112", "120"]
    assert all(o["verification_status"] == "unverified" for o in obs)


def test_pdf_corrected_report_matches_on_accession(client):
    original = upload(client, "synthetic_lab_report_2024.pdf")
    upload(client, "synthetic_lab_report_2024_corrected.pdf")
    old_ldl = by_test(observations_for(client, original["id"]), "ldl_cholesterol")[0]
    assert old_ldl["accession_id"] == "SYN-B-240115-0117"
    corr = [f for f in _flags(client) if f["kind"] == "possible_lab_correction"]
    assert len(corr) == 1 and corr[0]["detail"]["match_basis"] == "same_accession"


def test_accepted_observation_and_accepted_replacement_are_never_double_counted(client):
    original = upload(client, "synthetic_lab_report_2024.pdf")
    old_ldl = by_test(observations_for(client, original["id"]), "ldl_cholesterol")[0]
    assert accept(client, old_ldl["id"]).status_code == 200
    corrected = upload(client, "synthetic_lab_report_2024_corrected.pdf")
    new_ldl = by_test(observations_for(client, corrected["id"]), "ldl_cholesterol")[0]

    # While the replacement question is open, neither value is used.
    assert accept(client, new_ldl["id"]).status_code == 409
    assert calc_inputs(client, "ldl_cholesterol") == []

    flag = next(f for f in _flags(client) if f["kind"] == "possible_lab_correction")
    client.post(f"/api/v1/flags/{flag['id']}/resolve", json={"resolution": "new_supersedes_existing"})
    assert accept(client, new_ldl["id"]).status_code == 200
    inputs = calc_inputs(client, "ldl_cholesterol")
    assert [(i["observation_id"], i["value"]) for i in inputs] == [(new_ldl["id"], 127.0)]


def test_boundary_excludes_a_version_with_a_successor_even_if_still_marked_accepted(client):
    """Defense in depth against a replacement inserted without superseding the original."""
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:  # bypass the application: insert a successor, leave original accepted
        conn.execute(text("""
            INSERT INTO observations (id, participant_id, source_location, entry_method, original_test_name,
                normalized_test_name, original_value, value_numeric, normalized_value, normalized_unit, value_origin,
                collection_date, collection_date_status, report_date_status, specimen_type, collection_method,
                collection_method_basis, extraction_status, verification_status, verified_at,
                verification_method, supersedes_observation_id, created_by)
            SELECT gen_random_uuid(), participant_id, source_location, entry_method, original_test_name,
                normalized_test_name, '47', 47, 47, normalized_unit, value_origin, collection_date,
                collection_date_status, report_date_status, specimen_type, collection_method,
                collection_method_basis, 'participant_correction', 'accepted', now(), 'participant_review', id,
                'participant'
            FROM observations WHERE id = :id"""), {"id": hdl["id"]})
    engine.dispose()
    values = [i["value"] for i in calc_inputs(client, "hdl_cholesterol")]
    assert values == [47.0]


def test_identical_results_under_two_accessions_in_one_document_are_flagged_not_double_counted(client):
    doc = upload(client, "two.csv", data=HEADER + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,ACC-1,Final\n"
                 + b"HDL-C,55,mg/dL,2024-02-01,SYN Lab,ACC-1,Final\n"
                 + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,ACC-2,Final\n"
                 + b"HDL-C,55,mg/dL,2024-02-01,SYN Lab,ACC-2,Final\n")
    flags = _flags(client)
    assert {f["detail"]["match_basis"] for f in flags} == {"same_document_different_accession"}
    result = client.post(f"/api/v1/documents/{doc['id']}/auto-accept").json()
    assert result["repeats_collapsed"] == 2
    assert len(calc_inputs(client, "ldl_cholesterol")) == 1
    r = client.get(f"/api/v1/documents/{doc['id']}/reconciliation").json()
    assert r["accession_identifiers_in_document"] == 2
    assert r["set_aside"]["same_result_two_accessions_in_report"] == 2
