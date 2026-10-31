from conftest import accept, observations_for, upload


def _accept_all(client, doc_id):
    for o in observations_for(client, doc_id):
        if not o["blocking_issues"]:
            assert accept(client, o["id"]).status_code == 200, o


def test_capillary_and_venous_are_separate_series(client):
    _accept_all(client, upload(client, "synthetic_venous_panel_2022.csv")["id"])
    _accept_all(client, upload(client, "synthetic_fingerprick_2023.csv")["id"])
    _accept_all(client, upload(client, "synthetic_lab_report_2024.pdf")["id"])

    body = client.get("/api/v1/series/total_cholesterol").json()
    methods = sorted(s["collection_method"] for s in body["series"])
    assert methods == ["capillary", "venous"]
    venous = next(s for s in body["series"] if s["collection_method"] == "venous")
    capillary = next(s for s in body["series"] if s["collection_method"] == "capillary")
    assert [p["collection_date"] for p in venous["points"]] == ["2022-05-10", "2024-01-15"]
    assert [p["value"] for p in capillary["points"]] == [205.0, 198.0]
    assert any("Capillary and venous" in n for n in body["notices"])


def test_differing_reference_ranges_are_kept_per_point_and_noticed(client):
    _accept_all(client, upload(client, "synthetic_venous_panel_2022.csv")["id"])
    _accept_all(client, upload(client, "synthetic_lab_report_2024.pdf")["id"])
    # Change one report's range through a correction to create a difference within one series.
    hdl = next(o for o in client.get("/api/v1/observations", params={"verification_status": "accepted"}).json()
               if o["normalized_test_name"] == "hdl_cholesterol" and o["collection_date"] == "2024-01-15")
    new = client.post(f"/api/v1/observations/{hdl['id']}/correct",
                      json={"reference_range": "40-60", "reason": "Range misread"}).json()
    accept(client, new["id"])
    body = client.get("/api/v1/series/hdl_cholesterol").json()
    (series,) = body["series"]
    assert [p["reference_range_raw"] for p in series["points"]] == [">39", "40-60"]
    assert any("Reference ranges differ" in n for n in series["notices"])


def test_lpa_units_are_never_merged(client):
    _accept_all(client, upload(client, "synthetic_venous_panel_2022.csv")["id"])
    _accept_all(client, upload(client, "synthetic_fingerprick_2023.csv")["id"])
    body = client.get("/api/v1/series/lipoprotein_a").json()
    assert sorted(s["unit"] for s in body["series"]) == ["mg/dL", "nmol/L"]
    assert any("cannot be reliably converted" in n for n in body["notices"])


def test_unverified_candidates_hidden_unless_requested(client):
    upload(client, "synthetic_venous_panel_2022.csv")
    assert client.get("/api/v1/series/total_cholesterol").json()["series"] == []
    body = client.get("/api/v1/series/total_cholesterol", params={"include_unverified": True}).json()
    (series,) = body["series"]
    assert series["points"][0]["verification_status"] == "unverified"
    assert any("Unverified candidates are included" in n for n in body["notices"])
