"""The calculation-input interface must return explicitly accepted observations only."""

from sqlalchemy.orm import Session

from conftest import accept, by_test, calc_inputs, observations_for, upload


def test_nothing_is_a_calculation_input_until_accepted(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    assert calc_inputs(client) == []
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    inputs = calc_inputs(client)
    assert [i["observation_id"] for i in inputs] == [hdl["id"]]
    assert inputs[0]["value"] == 48.0 and inputs[0]["unit"] == "mg/dL"
    assert inputs[0]["collection_method"] == "venous"


def test_rejected_superseded_and_blocked_never_appear(client):
    edge = upload(client, "synthetic_edge_cases.csv")
    panel = upload(client, "synthetic_venous_panel_2022.csv")
    edge_obs = observations_for(client, edge["id"])
    panel_obs = observations_for(client, panel["id"])

    # Blocked candidates cannot be accepted at all.
    for o in edge_obs:
        if o["blocking_issues"]:
            assert accept(client, o["id"]).status_code == 409

    # Rejected
    tg = by_test(panel_obs, "triglycerides")[0]
    client.post(f"/api/v1/observations/{tg['id']}/reject", json={"reason": "test"})
    # Superseded (accepted then corrected; the correction itself is still unverified)
    hdl = by_test(panel_obs, "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    corrected = client.post(f"/api/v1/observations/{hdl['id']}/correct",
                            json={"value": "47", "reason": "misread"}).json()

    ids = {i["observation_id"] for i in calc_inputs(client)}
    assert tg["id"] not in ids
    assert hdl["id"] not in ids
    assert corrected["id"] not in ids
    assert not ids & {o["id"] for o in edge_obs}

    accept(client, corrected["id"])
    assert corrected["id"] in {i["observation_id"] for i in calc_inputs(client)}


def test_accepted_observation_with_open_flag_is_withheld(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    assert hdl["id"] in {i["observation_id"] for i in calc_inputs(client, "hdl_cholesterol")}
    upload(client, "synthetic_venous_panel_2022.csv")  # duplicate report raises a flag on hdl
    assert calc_inputs(client, "hdl_cholesterol") == []
    detail = client.get(f"/api/v1/observations/{hdl['id']}").json()
    assert detail["eligible_for_calculation_inputs"] is False


def test_python_boundary_matches_http_boundary(client):
    from app.calc_inputs import calculation_input_observations
    from app.db import get_engine
    from app.deps import DEFAULT_PARTICIPANT_ID

    doc = upload(client, "synthetic_lab_report_2024.pdf")
    obs = observations_for(client, doc["id"])
    for o in obs[:3]:
        accept(client, o["id"])
    with Session(get_engine()) as session:
        rows = calculation_input_observations(session, DEFAULT_PARTICIPANT_ID)
    assert {str(r.id) for r in rows} == {o["id"] for o in obs[:3]}
    assert all(r.verification_status == "accepted" for r in rows)
