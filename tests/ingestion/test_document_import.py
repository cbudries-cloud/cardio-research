import hashlib

from conftest import by_test, fixture_bytes, observations_for, upload


def test_csv_import_preserves_original_and_source_location(client):
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    assert doc["parse_status"] == "parsed"
    assert doc["candidate_count"] == 8
    assert doc["sha256"] == hashlib.sha256(fixture_bytes("synthetic_venous_panel_2022.csv")).hexdigest()

    original = client.get(f"/api/v1/documents/{doc['id']}/original")
    assert original.status_code == 200
    assert original.content == fixture_bytes("synthetic_venous_panel_2022.csv")

    obs = observations_for(client, doc["id"])
    ldl = by_test(obs, "ldl_cholesterol")[0]
    assert ldl["original_test_name"] == "LDL Cholesterol (calculated)"
    assert ldl["original_value"] == "141"
    assert ldl["original_unit"] == "mg/dL"
    assert ldl["value_origin"] == "calculated"
    assert ldl["collection_date"] == "2022-05-10"
    assert ldl["report_date"] == "2022-05-12"
    assert ldl["specimen_type"] == "serum"
    assert ldl["collection_method"] == "venous"
    assert ldl["collection_method_basis"] == "stated_in_source"
    assert ldl["reference_range_raw"] == "<100"
    assert ldl["lab_flag_raw"] == "H"
    assert ldl["laboratory"] == "SYNTHETIC Reference Lab A"
    assert ldl["collection_conditions"] == "Fasting 12h"
    assert ldl["extraction_status"] == "extracted"
    assert ldl["verification_status"] == "unverified"
    assert ldl["source_location"]["kind"] == "csv_row"
    assert ldl["source_location"]["row_number"] == 3
    assert ldl["source_location"]["cells"][1] == "141"


def test_every_candidate_starts_unverified(client):
    doc = upload(client, "synthetic_lab_report_2024.pdf")
    obs = observations_for(client, doc["id"])
    assert obs and all(o["verification_status"] == "unverified" for o in obs)


def test_pdf_import_extracts_rows_with_page_and_bbox(client):
    doc = upload(client, "synthetic_lab_report_2024.pdf")
    # HbA1c inherits "Specimen: Serum" from the header: a SPEC-1 conflict (D-024).
    assert doc["parse_status"] == "parsed_with_issues"
    assert doc["page_count"] == 1
    obs = observations_for(client, doc["id"])
    assert len(obs) == 8  # section headings are not results
    lpa = by_test(obs, "lipoprotein_a")[0]
    assert (lpa["original_value"], lpa["original_unit"]) == ("92", "nmol/L")
    assert lpa["collection_date"] == "2024-01-15"
    assert lpa["collection_method"] == "venous"
    loc = lpa["source_location"]
    assert loc["kind"] == "pdf_line" and loc["page"] == 1 and len(loc["bbox"]) == 4
    assert "Lipoprotein(a)" in loc["text"]

    image = client.get(f"/api/v1/documents/{doc['id']}/pages/1/image")
    assert image.status_code == 200 and image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/v1/documents/{doc['id']}/pages/2/image").status_code == 404


def test_image_only_pdf_reports_limitation_and_creates_no_candidates(client):
    doc = upload(client, "synthetic_scanned_image_only.pdf")
    assert doc["parse_status"] == "no_text_layer"
    assert "OCR is not implemented" in doc["parse_message"]
    assert doc["candidate_count"] == 0


def test_unsupported_layouts_report_limitation(client):
    pdf = upload(client, "synthetic_unsupported_letter.pdf")
    csv = upload(client, "synthetic_unsupported_layout.csv")
    assert pdf["parse_status"] == csv["parse_status"] == "unsupported_layout"
    assert pdf["candidate_count"] == csv["candidate_count"] == 0
    assert "manually" in pdf["parse_message"] and "manually" in csv["parse_message"]


def test_unsupported_format_is_stored_but_not_parsed(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post("/api/v1/documents", files={"file": ("photo.png", png, "image/png")})
    assert r.status_code == 201
    body = r.json()
    assert body["document_format"] == "unsupported"
    assert body["parse_status"] == "unsupported_format"
    assert client.get(f"/api/v1/documents/{body['id']}/original").content == png


def test_missing_units_block_acceptance(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    tg = by_test(observations_for(client, doc["id"]), "triglycerides")[0]
    assert tg["original_unit"] is None and tg["normalized_unit"] is None
    assert "missing_unit" in tg["blocking_issues"]
    assert tg["extraction_status"] == "extracted_with_issues"
    r = client.post(f"/api/v1/observations/{tg['id']}/accept", json={"confirm_source_matches": True})
    assert r.status_code == 409
    assert "missing_unit" in r.json()["info"]["blocking_issues"]


def test_ambiguous_dates_stay_unknown_and_block(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    assert doc["parse_status"] == "parsed_with_issues"
    obs = observations_for(client, doc["id"])
    hdl = by_test(obs, "hdl_cholesterol")[0]
    assert hdl["collection_date"] is None
    assert hdl["collection_date_raw"] == "04/06/2024"
    assert hdl["collection_date_status"] == "ambiguous"
    assert "ambiguous_collection_date" in hdl["blocking_issues"]
    tc = by_test(obs, "total_cholesterol")[0]
    assert tc["collection_date_raw"] == "06/04/24" and tc["collection_date"] is None


def test_declared_date_order_resolves_numeric_dates(client):
    doc = upload(client, "synthetic_edge_cases.csv", date_order="MDY")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    assert hdl["collection_date"] == "2024-04-06"
    assert hdl["collection_date_interpretation"] == "declared_order_MDY"
    assert "ambiguous_collection_date" not in hdl["extraction_issues"]


def test_unknown_specimen_type_is_preserved_as_unknown(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    obs = observations_for(client, doc["id"])
    lpa = by_test(obs, "lipoprotein_a")[0]
    assert lpa["specimen_type"] == "unknown"
    assert lpa["specimen_type_raw"] == "Specimen B"
    assert lpa["collection_method"] == "unknown"
    assert "unknown_specimen_type" in lpa["extraction_issues"]
    # Unknown specimen is a warning, not a blocker.
    assert "unknown_specimen_type" not in lpa["blocking_issues"]


def test_non_numeric_and_unrecognized_values_are_kept_verbatim(client):
    doc = upload(client, "synthetic_edge_cases.csv")
    obs = observations_for(client, doc["id"])
    apob = by_test(obs, "apolipoprotein_b")[0]
    assert apob["original_value"] == "See note" and apob["value_numeric"] is None
    assert "non_numeric_value" in apob["blocking_issues"]
    unknown = [o for o in obs if o["original_test_name"] == "Analyte X-17"][0]
    assert unknown["normalized_test_name"] is None
    assert "unrecognized_test_name" in unknown["extraction_issues"]


def test_capillary_declared_at_upload_is_distinguishable(client):
    doc = upload(client, "synthetic_edge_cases.csv", collection_method="capillary")
    tg = by_test(observations_for(client, doc["id"]), "triglycerides")[0]
    assert tg["collection_method"] == "capillary"
    assert tg["collection_method_basis"] == "declared_at_upload"
