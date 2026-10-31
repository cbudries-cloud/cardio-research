from conftest import accept, by_test, observations_for, upload


def _open_flags(client):
    return client.get("/api/v1/flags").json()


def test_duplicate_report_is_flagged_not_merged(client):
    first = upload(client, "synthetic_venous_panel_2022.csv")
    second = upload(client, "synthetic_venous_panel_2022.csv")
    assert second["duplicate_of_document_id"] == first["id"]
    assert second["candidate_count"] == 8  # nothing merged or dropped

    flags = _open_flags(client)
    assert sum(f["kind"] == "duplicate_document" for f in flags) == 1
    dupes = [f for f in flags if f["kind"] == "possible_duplicate"]
    assert len(dupes) == 8

    new_hdl = by_test(observations_for(client, second["id"]), "hdl_cholesterol")[0]
    old_hdl = by_test(observations_for(client, first["id"]), "hdl_cholesterol")[0]
    r = accept(client, new_hdl["id"])
    assert r.status_code == 409 and r.json()["info"]["open_flags"]
    # The original is also blocked while the question is open.
    assert accept(client, old_hdl["id"]).status_code == 409

    flag = next(f for f in dupes if f["observation_id"] == new_hdl["id"])
    assert set(flag["allowed_resolutions"]) == {"distinct_measurements", "reject_new"}
    r = client.post(f"/api/v1/flags/{flag['id']}/resolve", json={"resolution": "reject_new", "note": "Same report"})
    assert r.status_code == 200
    assert client.get(f"/api/v1/observations/{new_hdl['id']}").json()["observation"]["verification_status"] == "rejected"
    assert accept(client, old_hdl["id"]).status_code == 200


def test_invalid_resolution_rejected(client):
    upload(client, "synthetic_venous_panel_2022.csv")
    upload(client, "synthetic_venous_panel_2022.csv")
    flag = next(f for f in _open_flags(client) if f["kind"] == "possible_duplicate")
    r = client.post(f"/api/v1/flags/{flag['id']}/resolve", json={"resolution": "new_supersedes_existing"})
    assert r.status_code == 422


def test_lab_corrected_report_is_linked_only_after_confirmation(client):
    original = upload(client, "synthetic_lab_report_2024.pdf")
    old_ldl = by_test(observations_for(client, original["id"]), "ldl_cholesterol")[0]
    assert accept(client, old_ldl["id"]).status_code == 200

    corrected = upload(client, "synthetic_lab_report_2024_corrected.pdf")
    assert corrected["duplicate_of_document_id"] is None  # different file
    new_obs = observations_for(client, corrected["id"])
    new_ldl = by_test(new_obs, "ldl_cholesterol")[0]
    assert new_ldl["reported_as_corrected"] is True
    assert new_ldl["original_value"] == "127"

    flags = _open_flags(client)
    corr = [f for f in flags if f["kind"] == "possible_lab_correction"]
    assert len(corr) == 1 and corr[0]["observation_id"] == new_ldl["id"]
    assert corr[0]["related_observation_id"] == old_ldl["id"]
    # Unchanged rows in the corrected report are possible duplicates, not corrections.
    assert sum(f["kind"] == "possible_duplicate" for f in flags) == 7

    # Accepted original is withheld from calculation inputs while the question is open.
    ids = [c["observation_id"] for c in client.get("/api/v1/calculation-inputs/observations").json()]
    assert old_ldl["id"] not in ids

    r = client.post(f"/api/v1/flags/{corr[0]['id']}/resolve",
                    json={"resolution": "new_supersedes_existing", "note": "Lab issued corrected report"})
    assert r.status_code == 200
    old_detail = client.get(f"/api/v1/observations/{old_ldl['id']}").json()
    assert old_detail["observation"]["verification_status"] == "superseded"
    assert old_detail["observation"]["original_value"] == "131"  # preserved
    new_detail = client.get(f"/api/v1/observations/{new_ldl['id']}").json()
    assert new_detail["observation"]["supersedes_observation_id"] == old_ldl["id"]
    assert new_detail["observation"]["correction_kind"] == "lab_issued_correction"
    assert new_detail["observation"]["verification_status"] == "unverified"  # still needs review
    assert accept(client, new_ldl["id"]).status_code == 200


def test_conflicting_value_can_be_independent_measurements(client):
    upload(client, "synthetic_venous_panel_2022.csv")
    r = client.post("/api/v1/observations", json={
        "test_name": "HDL Cholesterol", "value": "55", "unit": "mg/dL", "collection_date": "2022-05-10",
        "collection_method": "venous"})
    manual = r.json()
    flag = next(f for f in _open_flags(client) if f["observation_id"] == manual["id"])
    assert flag["kind"] == "conflicting_value"
    client.post(f"/api/v1/flags/{flag['id']}/resolve",
                json={"resolution": "distinct_measurements", "note": "Second draw that afternoon"})
    assert accept(client, manual["id"]).status_code == 200


def test_capillary_and_venous_same_day_are_not_flagged_as_duplicates(client):
    upload(client, "synthetic_venous_panel_2022.csv")
    client.post("/api/v1/observations", json={
        "test_name": "HDL Cholesterol", "value": "44", "unit": "mg/dL", "collection_date": "2022-05-10",
        "collection_method": "capillary", "specimen": "Dried blood spot"})
    assert _open_flags(client) == []
