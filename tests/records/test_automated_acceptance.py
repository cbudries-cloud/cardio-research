"""Automated acceptance: labelled, limited to rows that pass the source checks, never silent."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from conftest import TEST_DB, accept, by_test, calc_inputs, observations_for, upload

HEADER = b"Test,Result,Units,Collection Date,Lab,Accession\n"


def _auto(client, doc_id):
    r = client.post(f"/api/v1/documents/{doc_id}/auto-accept")
    assert r.status_code == 200, r.text
    return r.json()


def test_rows_passing_checks_are_accepted_and_labelled(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    result = _auto(client, doc["id"])
    obs = observations_for(client, doc["id"])
    accepted = [o for o in obs if o["verification_status"] == "accepted"]
    assert result["accepted"] == len(accepted) > 0
    assert all(o["verification_method"] == "automated_check" for o in accepted)
    assert all(o["verification_note"].startswith("Accepted by automated check, not reviewed") for o in accepted)
    apob = by_test(obs, "apolipoprotein_b")[0]
    assert apob["verification_status"] == "accepted"
    (row,) = calc_inputs(client, "apolipoprotein_b")
    assert row["verification_method"] == "automated_check"


def test_rows_failing_any_check_stay_unverified(client):
    doc = upload(client, "synthetic_range_split_report.pdf")  # no date order: dates ambiguous
    result = _auto(client, doc["id"])
    assert result["accepted"] == 0
    assert result["reasons_left"]["blocking_issue"] == result["left_for_review"]
    doc = upload(client, "note.csv", data=HEADER + b"Vitamin D 25-OH,SEE NOTE,ng/mL,2024-02-01,SYN Lab,\n"
                 + b"Urine Glucose,NEGATIVE,,2024-02-01,SYN Lab,\n")
    result = _auto(client, doc["id"])
    rows = {o["original_value"]: o for o in observations_for(client, doc["id"])}
    assert rows["SEE NOTE"]["verification_status"] == "unverified"  # free text: never accepted automatically
    assert rows["SEE NOTE"]["result_type"] == "text"
    assert rows["NEGATIVE"]["verification_status"] == "accepted"  # a categorical result needs no number or unit
    assert result["reasons_left"].get("free_text_result") == 1


def test_open_conflict_blocks_automated_acceptance(client):
    upload(client, "a.csv", data=HEADER + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,\n")
    doc = upload(client, "b.csv", data=HEADER + b"LDL-C,131,mg/dL,2024-02-01,SYN Lab,\n")
    result = _auto(client, doc["id"])
    assert result["accepted"] == 0 and result["reasons_left"] == {"open_flag": 1}


def test_result_printed_twice_in_one_report_is_counted_once(client):
    doc = upload(client, "twice.csv", data=HEADER
                 + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,ACC-1\n"
                 + b"LDL-C,120,mg/dL,2024-02-01,SYN Lab,ACC-1\n")
    result = _auto(client, doc["id"])
    assert result == {"repeats_collapsed": 1, "reprints_corroborating": 0, "accepted": 1, "left_for_review": 0,
                      "reasons_left": {}}
    assert len(calc_inputs(client, "ldl_cholesterol")) == 1
    statuses = sorted(o["verification_status"] for o in observations_for(client, doc["id"]))
    assert statuses == ["accepted", "rejected"]


def test_participant_acceptance_is_labelled_participant_review(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    assert accept(client, hdl["id"]).json()["verification_method"] == "participant_review"


def test_participant_can_confirm_an_automated_acceptance_once(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    _auto(client, doc["id"])
    obs_id = by_test(observations_for(client, doc["id"]), "apolipoprotein_b")[0]["id"]
    assert client.post(f"/api/v1/observations/{obs_id}/confirm", json={"confirm_source_matches": False}).status_code == 422
    r = client.post(f"/api/v1/observations/{obs_id}/confirm", json={"confirm_source_matches": True})
    assert r.status_code == 200 and r.json()["verification_method"] == "participant_review"
    assert client.post(f"/api/v1/observations/{obs_id}/confirm", json={"confirm_source_matches": True}).status_code == 409
    engine = create_engine(TEST_DB)
    with pytest.raises(DBAPIError, match="verification_method may only be set once"):
        with engine.begin() as conn:  # bypass the application: a confirmation cannot be undone
            conn.execute(text("UPDATE observations SET verification_method = 'automated_check' WHERE id = :id"),
                         {"id": obs_id})
    engine.dispose()


def test_acceptance_without_a_verification_method_never_reaches_calculations(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:  # bypass the application: accept without saying how
        conn.execute(text("UPDATE observations SET verification_status = 'accepted', verified_at = now() "
                          "WHERE id = :id"), {"id": hdl["id"]})
    engine.dispose()
    assert calc_inputs(client, "hdl_cholesterol") == []
