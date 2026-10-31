"""Range-split report layout (In Range / Out of Range columns) and re-extraction.

Both fixtures are synthetic reproductions of a layout observed in a real report; only its
structure (column headings, positions, panel heading lines) was reproduced, never its values.
"""

import pytest

from conftest import accept, by_test, calc_inputs, observations_for, upload

FIXTURES = ["synthetic_range_split_report.pdf", "synthetic_range_split_with_previous.pdf"]


@pytest.mark.parametrize("name", FIXTURES)
def test_value_is_read_from_whichever_range_column_holds_it(client, name):
    doc = upload(client, name, date_order="MDY")
    obs = [o for o in observations_for(client, doc["id"]) if o["reported_as"] == "current"]
    assert len(obs) == 16  # panel headings, "Fasting:" and comments are not results
    tc = by_test(obs, "total_cholesterol")[0]
    assert (tc["original_value"], tc["lab_flag_raw"], tc["original_unit"]) == ("212", "H", "mg/dL")
    assert tc["reference_range_raw"] == "<200"
    hdl = by_test(obs, "hdl_cholesterol")[0]
    assert (hdl["original_value"], hdl["lab_flag_raw"]) == ("55", None)
    assert hdl["reference_range_raw"] == "> OR = 40"


def test_previous_result_column_is_never_read_as_the_result(client):
    doc = upload(client, "synthetic_range_split_with_previous.pdf", date_order="MDY")
    obs = [o for o in observations_for(client, doc["id"]) if o["reported_as"] == "current"]
    values = {o["normalized_test_name"]: o["original_value"] for o in obs}
    assert values["total_cholesterol"] == "212"  # previous column holds 198
    assert values["ldl_cholesterol"] == "134"  # previous column holds 121
    assert values["hemoglobin_a1c"] == "5.4"  # previous column holds 5.5
    assert not any("02/10/2024" in (o["original_value"] or "") for o in obs)


def test_unit_and_calculation_marker_come_from_the_reference_cell(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    ldl = by_test(observations_for(client, doc["id"]), "ldl_cholesterol")[0]
    assert ldl["original_unit"] == "mg/dL"
    assert ldl["method"] == "(calc)"
    assert ldl["value_origin"] == "calculated"
    assert ldl["reference_range_raw"] is None  # stated only in an indented comment
    assert ldl["blocking_issues"] == []


def test_panel_collected_line_sets_the_collection_date_for_its_rows(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    obs = observations_for(client, doc["id"])
    assert by_test(obs, "lipoprotein_a")[0]["collection_date"] == "2025-03-06"
    assert by_test(obs, "apolipoprotein_b")[0]["collection_date"] == "2025-03-04"
    lpa = by_test(obs, "lipoprotein_a")[0]
    assert "Collected: 03/06/2025" in lpa["inherited_metadata"]["collection_date"]["text"]
    assert lpa["accession_id"] == "SYNRS0000001"
    # "Fasting: YES" was stated under the 03/04 draw; it does not carry over to the 03/06 draw.
    assert lpa["collection_conditions"] is None
    assert by_test(obs, "apolipoprotein_b")[0]["collection_conditions"] == "YES"


def test_reference_printed_inside_the_result_column_is_split_off(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    obs = observations_for(client, doc["id"])
    crp = by_test(obs, "hs_crp")[0]
    assert (crp["original_value"], crp["original_unit"], crp["reference_range_raw"]) == ("0.8", "mg/L", "<1.0")
    assert crp["blocking_issues"] == []
    # The margin-aligned comment under each row is not a candidate.
    assert not any("performance characteristics" in (o["original_value"] or "") for o in obs)


def test_reference_starting_in_the_out_of_range_column_is_not_a_second_result(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    cr = by_test(observations_for(client, doc["id"]), "creatinine")[0]
    assert (cr["original_value"], cr["lab_flag_raw"], cr["original_unit"]) == ("0.92", None, "mg/dL")
    assert cr["reference_range_raw"] == "0.60-1.29"


def test_slightly_indented_sub_results_are_kept(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    sub = [o for o in observations_for(client, doc["id"]) if o["original_test_name"] == "LDL PARTICLE NUMBER"]
    assert len(sub) == 1 and (sub[0]["original_value"], sub[0]["lab_flag_raw"]) == ("1650", "H")


def test_without_declared_order_dates_stay_ambiguous(client):
    doc = upload(client, "synthetic_range_split_report.pdf")
    obs = observations_for(client, doc["id"])
    assert all(o["collection_date"] is None for o in obs)
    assert all("ambiguous_collection_date" in o["blocking_issues"] for o in obs)


def test_categorical_result_is_kept_as_a_category_not_blocked(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    glucose = [o for o in observations_for(client, doc["id"]) if o["original_value"] == "NEGATIVE"]
    assert len(glucose) == 1
    g = glucose[0]
    assert g["result_type"] == "categorical" and g["value_numeric"] is None
    assert "non_numeric_value" not in g["extraction_issues"] and "missing_unit" not in g["extraction_issues"]
    assert g["blocking_issues"] == []


def test_bounded_result_keeps_its_comparator_and_is_not_an_exact_value(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    tpo = [o for o in observations_for(client, doc["id"]) if o["original_test_name"] == "THYROID PEROXIDASE ANTIBODIES"][0]
    assert tpo["result_type"] == "bounded"
    assert (tpo["original_value"], tpo["value_comparator"], tpo["value_numeric"]) == ("<1", "<", 1.0)
    assert "value_has_comparator" in tpo["extraction_issues"]


@pytest.mark.parametrize("name,where,part", [("SEX HORMONE BINDING GLOBULIN", "after", "GLOBULIN"),
                                             ("THYROID PEROXIDASE ANTIBODIES", "before", "THYROID PEROXIDASE")])
def test_wrapped_test_names_are_joined_and_both_source_lines_kept(client, name, where, part):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    obs = observations_for(client, doc["id"])
    (o,) = [o for o in obs if o["original_test_name"] == name]
    cont = o["source_location"]["name_continuation"]
    assert (cont["text"], cont["position"]) == (part, where)
    assert part not in o["source_location"]["text"] or where == "before"  # the row line itself is unchanged
    assert "test_name_joined_from_wrapped_lines" in o["extraction_issues"]
    assert not any(x["original_test_name"] in ("GLOBULIN", "THYROID PEROXIDASE") for x in obs)


# --- Re-extraction ---------------------------------------------------------------------


def _reextract(client, doc_id, **form):
    return client.post(f"/api/v1/documents/{doc_id}/reextract", data=form)


def test_reextract_replaces_unreviewed_candidates_and_keeps_them_auditable(client):
    doc = upload(client, "synthetic_range_split_report.pdf")
    before = observations_for(client, doc["id"])
    assert all(o["collection_date"] is None for o in before)

    r = _reextract(client, doc["id"], date_order="MDY")
    assert r.status_code == 200, r.text
    assert r.json()["candidate_count"] == 16
    assert r.json()["declared_date_order"] == "MDY"

    detail = client.get(f"/api/v1/documents/{doc['id']}").json()
    assert detail["replaced_candidate_count"] == 16
    assert {o["id"] for o in detail["observations"]}.isdisjoint({o["id"] for o in before})
    assert all(o["collection_date"] for o in detail["observations"])

    old = client.get(f"/api/v1/observations/{before[0]['id']}").json()
    assert old["observation"]["verification_status"] == "rejected"
    assert old["observation"]["verification_note"].startswith("Replaced by re-extraction")
    assert old["observation"]["original_value"] == before[0]["original_value"]  # row unchanged
    assert "observation.rejected" in [e["action"] for e in old["audit"]]


def test_reextracted_document_does_not_double_count(client):
    doc = upload(client, "synthetic_range_split_report.pdf")
    _reextract(client, doc["id"], date_order="MDY")
    apob = by_test(observations_for(client, doc["id"]), "apolipoprotein_b")
    assert len(apob) == 1
    assert accept(client, apob[0]["id"]).status_code == 200
    assert len(calc_inputs(client, "apolipoprotein_b")) == 1


def test_reextract_is_refused_once_anything_is_reviewed(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    assert accept(client, hdl["id"]).status_code == 200
    r = _reextract(client, doc["id"])
    assert r.status_code == 409
    assert client.get(f"/api/v1/documents/{doc['id']}").json()["reextract_allowed"] is False


def test_reextract_without_date_order_keeps_the_earlier_declaration(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    r = _reextract(client, doc["id"])
    assert r.json()["declared_date_order"] == "MDY"



def test_previous_results_become_labelled_historical_rows(client):
    doc = upload(client, "synthetic_range_split_with_previous.pdf", date_order="MDY")
    hist = [o for o in observations_for(client, doc["id"]) if o["reported_as"] == "historical_in_later_report"]
    assert {(o["normalized_test_name"], o["original_value"], o["collection_date"]) for o in hist} == {
        ("total_cholesterol", "198", "2024-02-10"), ("hdl_cholesterol", "51", "2024-02-10"),
        ("ldl_cholesterol", "121", "2024-02-10"), ("apolipoprotein_b", "99", "2024-02-10"),
        ("hemoglobin_a1c", "5.5", "2024-02-10"),
    }
    for o in hist:
        assert o["accession_id"] is None and o["reference_range_raw"] is None  # not stated for them
        assert o["source_location"]["column"] == "previous_result"
        assert "unit" in o["inherited_metadata"]


def test_reconciliation_accounts_for_every_row(client):
    doc = upload(client, "synthetic_range_split_with_previous.pdf", date_order="MDY")
    r = client.get(f"/api/v1/documents/{doc['id']}/reconciliation").json()
    assert r["results_found"] == {"rows_kept": 21, "current": 16, "historical_in_later_report": 5,
                                  "recognized_test_name": 17, "unfamiliar_test_name_kept": 4}
    assert r["verification"]["unverified"] == 21
    assert r["omitted_numeric_lines"]["by_reason"]["indented_comment"] >= 1
    assert all(line["reason"] != "indented_comment" for line in r["omitted_numeric_lines"]["lines"])


def test_reextract_withdraws_automated_acceptances_but_not_participant_reviews(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    client.post(f"/api/v1/documents/{doc['id']}/auto-accept")
    r = _reextract(client, doc["id"])
    assert r.status_code == 200, r.text
    assert r.json()["accepted_count"] == 0
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    assert accept(client, hdl["id"]).status_code == 200
    assert _reextract(client, doc["id"]).status_code == 409


def test_reprinted_previous_result_matching_the_original_is_kept_as_corroboration(client):
    earlier = upload(client, "earlier.csv", data=b"Test,Result,Units,Collection Date,Lab\n"
                     b"Apolipoprotein B,99,mg/dL,2024-02-10,SY1\n")
    later = upload(client, "synthetic_range_split_with_previous.pdf", date_order="MDY")
    result = client.post(f"/api/v1/documents/{later['id']}/auto-accept").json()
    assert result["reprints_corroborating"] == 1
    reprint = [o for o in observations_for(client, later["id"])
               if o["reported_as"] == "historical_in_later_report" and o["normalized_test_name"] == "apolipoprotein_b"][0]
    assert reprint["verification_status"] == "rejected" and "corroboration" in reprint["verification_note"]
    original = by_test(observations_for(client, earlier["id"]), "apolipoprotein_b")[0]
    assert original["verification_status"] == "unverified"  # its own document's check accepts it
    r = client.get(f"/api/v1/documents/{later['id']}/reconciliation").json()
    assert r["set_aside"]["reprint_corroborating_original_report"] == 1


def test_comment_lines_are_kept_with_the_result_they_annotate(client):
    doc = upload(client, "synthetic_range_split_report.pdf", date_order="MDY")
    ldl = by_test(observations_for(client, doc["id"]), "ldl_cholesterol")[0]
    comments = ldl["source_location"]["comments"]
    assert comments[0] == "Reference range: <100"
    assert any("Desirable range" in c for c in comments)


@pytest.mark.parametrize("line,expected", [("Accession AB123456C", "AB123456C"), ("Accession Number SYN-0001", "SYN-0001"),
                                           ("Accession", None), ("Accession pending review", None)])
def test_accession_label_without_colon(line, expected):
    from app.ingestion.pdf_parser import _ACCESSION_NO_COLON
    m = _ACCESSION_NO_COLON.match(line)
    assert (m.group(1) if m else None) == expected
