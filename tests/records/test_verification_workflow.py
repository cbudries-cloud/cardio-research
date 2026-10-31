import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from conftest import TEST_DB, accept, by_test, observations_for, upload


def test_accept_requires_explicit_confirmation(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    r = client.post(f"/api/v1/observations/{hdl['id']}/accept", json={"confirm_source_matches": False})
    assert r.status_code == 422
    r = accept(client, hdl["id"])
    assert r.status_code == 200
    assert r.json()["verification_status"] == "accepted"
    assert r.json()["verified_at"] is not None
    assert accept(client, hdl["id"]).status_code == 409  # cannot accept twice


def test_correction_preserves_previous_value_and_writes_audit(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    tg = by_test(observations_for(client, doc["id"]), "triglycerides")[0]

    r = client.post(f"/api/v1/observations/{tg['id']}/correct",
                    json={"unit": "mg/dL", "reason": "Unit printed in page header, missed by parser"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != tg["id"]
    assert new["supersedes_observation_id"] == tg["id"]
    assert new["original_unit"] == "mg/dL" and new["normalized_unit"] == "mg/dL"
    assert new["extraction_status"] == "participant_correction"
    assert new["correction_kind"] == "extraction_error"
    assert new["blocking_issues"] == []

    old_detail = client.get(f"/api/v1/observations/{tg['id']}").json()
    assert old_detail["observation"]["verification_status"] == "superseded"
    assert old_detail["observation"]["original_unit"] is None  # previous value intact
    assert old_detail["superseded_by"] == new["id"]

    new_detail = client.get(f"/api/v1/observations/{new['id']}").json()
    assert [h["id"] for h in new_detail["history"]] == [tg["id"]]
    corrected = [a for a in new_detail["audit"] if a["action"] == "observation.corrected"][0]
    assert corrected["detail"]["before"]["original_unit"] is None
    assert corrected["detail"]["after"]["original_unit"] == "mg/dL"
    assert corrected["detail"]["reason"].startswith("Unit printed")

    assert accept(client, new["id"]).status_code == 200


def test_ambiguous_date_resolved_by_participant(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    assert accept(client, hdl["id"]).status_code == 409
    r = client.post(f"/api/v1/observations/{hdl['id']}/correct",
                    json={"collection_date": "2024-06-04", "reason": "Report uses day-first dates"})
    new = r.json()
    assert new["collection_date"] == "2024-06-04"
    assert new["collection_date_status"] == "participant_resolved"
    assert new["collection_date_raw"] == "04/06/2024"  # raw text kept
    assert accept(client, new["id"]).status_code == 200


def test_correcting_an_accepted_observation_supersedes_it(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    r = client.post(f"/api/v1/observations/{hdl['id']}/correct",
                    json={"value": "46", "reason": "Misread 48 for 46"})
    assert r.status_code == 201
    assert client.get(f"/api/v1/observations/{hdl['id']}").json()["observation"]["verification_status"] == "superseded"
    # A superseded row cannot be corrected again; correct the current version instead.
    again = client.post(f"/api/v1/observations/{hdl['id']}/correct", json={"value": "47", "reason": "x"})
    assert again.status_code == 409


def test_reject_and_withdraw(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    obs = observations_for(client, doc["id"])
    tg, hdl = by_test(obs, "triglycerides")[0], by_test(obs, "hdl_cholesterol")[0]
    r = client.post(f"/api/v1/observations/{tg['id']}/reject", json={"reason": "Not my result"})
    assert r.json()["verification_status"] == "rejected"
    assert accept(client, tg["id"]).status_code == 409

    accept(client, hdl["id"])
    r = client.post(f"/api/v1/observations/{hdl['id']}/reject", json={"reason": "Withdrawn"})
    assert r.json()["verification_status"] == "rejected"
    actions = [a["action"] for a in client.get(f"/api/v1/observations/{hdl['id']}").json()["audit"]]
    assert "observation.withdrawn" in actions and "observation.accepted" in actions


def test_manual_entry_for_image_only_document(client):
    doc = upload(client, "synthetic_scanned_image_only.pdf")
    r = client.post("/api/v1/observations", json={
        "source_document_id": doc["id"], "source_page": 1, "source_note": "third line",
        "test_name": "Cholesterol, Total", "value": "201", "unit": "mg/dL",
        "collection_date": "2021-11-02", "reference_range": "<200", "collection_method": "venous",
    })
    assert r.status_code == 201, r.text
    obs = r.json()
    assert obs["entry_method"] == "manual"
    assert obs["extraction_status"] == "manual_entry"
    assert obs["verification_status"] == "unverified"
    assert obs["normalized_test_name"] == "total_cholesterol"
    assert obs["collection_method_basis"] == "participant_entered"
    assert obs["source_location"] == {"kind": "manual", "page": 1, "note": "third line"}
    assert accept(client, obs["id"]).status_code == 200


def test_manual_entry_without_document_is_marked(client):
    r = client.post("/api/v1/observations", json={
        "test_name": "LDL-C", "value": "120", "unit": "mg/dL", "collection_date": "2020-01-01"})
    assert "no_source_document" in r.json()["extraction_issues"]


@pytest.mark.parametrize("sql", [
    "UPDATE observations SET original_value = '999'",
    "UPDATE observations SET collection_date = '2000-01-01'",
    "DELETE FROM observations",
    "UPDATE audit_events SET action = 'tampered'",
    "DELETE FROM audit_events",
    "DELETE FROM source_documents",
])
def test_database_refuses_silent_rewrites(client, sql):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    accept(client, by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]["id"])
    engine = create_engine(TEST_DB)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text(sql))
    engine.dispose()


def test_database_refuses_reviving_superseded_rows(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    tg = by_test(observations_for(client, doc["id"]), "triglycerides")[0]
    client.post(f"/api/v1/observations/{tg['id']}/correct", json={"unit": "mg/dL", "reason": "r"})
    engine = create_engine(TEST_DB)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE observations SET verification_status = 'accepted', verified_at = now() "
                              "WHERE id = :id"), {"id": tg["id"]})
    engine.dispose()


def test_participant_interpretations_survive_later_corrections(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    obs = observations_for(client, doc["id"])
    unknown = [o for o in obs if o["original_test_name"] == "Analyte X-17"][0]
    hdl = by_test(obs, "hdl_cholesterol")[0]

    mapped = client.post(f"/api/v1/observations/{unknown['id']}/correct",
                         json={"normalized_test_name": "insulin", "reason": "lab calls insulin X-17"}).json()
    later = client.post(f"/api/v1/observations/{mapped['id']}/correct",
                        json={"reference_range": "2-20", "reason": "range misread"}).json()
    assert later["normalized_test_name"] == "insulin"

    dated = client.post(f"/api/v1/observations/{hdl['id']}/correct",
                        json={"collection_date": "2024-06-04", "report_date": "2024-06-06", "reason": "day-first"}).json()
    later = client.post(f"/api/v1/observations/{dated['id']}/correct",
                        json={"flag": "L", "reason": "flag missed"}).json()
    assert later["collection_date"] == "2024-06-04" and later["collection_date_status"] == "participant_resolved"
    assert later["report_date"] == "2024-06-06" and later["report_date_status"] == "participant_resolved"
    assert later["blocking_issues"] == []
