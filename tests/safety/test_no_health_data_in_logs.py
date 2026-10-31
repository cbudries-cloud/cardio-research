"""Logs must not contain observation values, filenames, or exception messages."""

import logging

from conftest import accept, by_test, observations_for, upload

SENTINEL = "SENTINEL-VALUE-7731"


def test_normal_workflow_logs_no_values(client, caplog):
    caplog.set_level(logging.DEBUG)
    doc = upload(client, "synthetic_venous_panel_2022.csv")
    hdl = by_test(observations_for(client, doc["id"]), "hdl_cholesterol")[0]
    accept(client, hdl["id"])
    client.post(f"/api/v1/observations/{hdl['id']}/correct", json={"value": "4848", "reason": "r"})
    text = caplog.text
    for forbidden in ("synthetic_venous_panel_2022", "SYNTHETIC Reference Lab A", "4848", "HDL Cholesterol"):
        assert forbidden not in text


def test_unhandled_error_logs_type_only(client, caplog, monkeypatch):
    from app.services import records

    def boom(*args, **kwargs):
        raise ValueError(f"could not process value {SENTINEL}")

    monkeypatch.setattr(records, "import_document", boom)
    caplog.set_level(logging.DEBUG)
    r = client.post("/api/v1/documents", files={"file": ("x.csv", b"Test,Result\nA,1\n", "text/csv")})
    assert r.status_code == 500
    assert SENTINEL not in r.text
    assert "error_id" in r.json()
    assert "ValueError" in caplog.text
    assert SENTINEL not in caplog.text
