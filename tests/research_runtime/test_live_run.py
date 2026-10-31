"""Live run of the ApoB / LDL-P investigation on synthetic records: readiness gates, the scrubbed
payload, per-run approval bound to the exact request, single use, and citation checking.
No network: the provider's transport is replaced by a fake."""

import json

import pytest
from sqlalchemy import create_engine, text

from conftest import TEST_DB, upload

from app.research import live_run, providers

HEADER = b"Test,Result,Units,Collection Date,Lab,Reference Range,Flag,Method,Accession\n"
DRAW = (b"LDL PARTICLE NUMBER,1500,nmol/L,2025-01-10,SYA,<1138,H,Ion Mobility,ACC12345\n"
        b"Apolipoprotein B,66,mg/dL,2025-01-10,SYB,<90,,,ACC12345\n"
        b"LDL Cholesterol (direct),80,mg/dL,2025-01-10,SYA,<100,,,ACC12345\n"
        b"LDL SMALL,240,nmol/L,2025-01-10,SYA,<142,H,Ion Mobility,ACC12345\n"
        b"Hemoglobin A1c,5.3,%,2025-01-10,SYB,<5.7,,,ACC12345\n")


@pytest.fixture
def configured(monkeypatch, tmp_path):
    key = tmp_path / "anthropic_api_key"
    key.write_text("sk-test-not-real\n")
    monkeypatch.setenv("CARDIO_RESEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("CARDIO_LLM_API_KEY_FILE", str(key))
    sent = []
    monkeypatch.setattr(live_run, "start", lambda run_id: live_run.execute(run_id))  # synchronous in tests
    return sent


def _fake_send(sent, output):
    def send(self, body, timeout_s):
        sent.append(body)
        return providers.LiveResponse("succeeded", {
            "id": "msg_test", "model": "claude-opus-5-5", "stop_reason": "end_turn",
            "usage": {"input_tokens": 9000, "output_tokens": 3000},
            "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(output)}]}, 12.0)
    return send


def _setup(client):
    doc = upload(client, "draw.csv", data=HEADER + DRAW)
    assert client.post(f"/api/v1/documents/{doc['id']}/auto-accept").status_code == 200
    return doc


def _confirm_supporting(client):
    for s in client.get("/api/v1/research/apob-ldlp/readiness").json()["supporting"]:
        if s["verification_method"] != "participant_review":
            r = client.post(f"/api/v1/observations/{s['observation_id']}/confirm", json={"confirm_source_matches": True})
            assert r.status_code == 200, r.text


def _approval(run, **over):
    return {"payload_sha256": run["payload_sha256"], "provider": run["provider"], "model": run["model"],
            "endpoint": run["endpoint"], "approve_this_payload_for_this_run_only": True, **over}


def _s(t, o=(), e=(), r=(), inference=False):
    return {"statement": t, "is_inference": inference, "observation_refs": list(o), "evidence_refs": list(e),
            "rule_refs": list(r)}


def _good_output():
    s = _s
    return {
        "input_issues": [s("H1 lists missing evidence as contrary evidence.", r=["H1"])],
        "established": [s("LDL-P and ApoB were measured on the same draw.", ["O1", "O2"])],
        "competing_explanations": [{"explanation": "Cross-assay scale difference", "relation_to_supplied": "keeps H1",
                                    "rule_refs": ["H1"],
                                    "supporting": [s("Assays are not standardized.", e=["epstein-2025-apob-vs-ldlp"])],
                                    "contrary": [], "evidence_gaps": [s("No absolute comparison of the assays.", r=["H1"])],
                                    "assessment": s("Open.", ["O1"], inference=True)}],
        "remaining_uncertainty": [s("The ApoB assay is unidentified.", r=["R1"])],
        "distinguishing_information": [{"information": "Calibration documentation for each assay.",
                                        "explanations_distinguished": ["Cross-assay scale difference"], "evidence_refs": []}],
        "comparison_with_rules": {"differences_from_rules": [s("The outcome study used NMR.",
                                                                      e=["epstein-2025-apob-vs-ldlp/n-nmr-profiled-samples"])],
                                  "unchanged": [s("Measured once.", r=["R2"])]},
    }


def test_run_is_refused_until_supporting_observations_are_confirmed(client, configured):
    _setup(client)
    ready = client.get("/api/v1/research/apob-ldlp/readiness").json()
    assert ready["available"] and not ready["ready_to_prepare"]
    gate = next(g for g in ready["gates"] if g["id"] == "sources_confirmed")
    assert not gate["ok"] and "0 of 4" in gate["detail"]  # LDL-P, ApoB, LDL-C, flagged LDL small; not HbA1c
    assert client.post("/api/v1/research/live-runs").status_code == 409
    assert ready["provider"]["key_configured"] and "sk-test" not in json.dumps(ready)  # key never returned


def test_payload_excludes_identifiers_dates_and_unrelated_measurements(client, configured):
    _setup(client)
    _confirm_supporting(client)
    r = client.post("/api/v1/research/live-runs")
    assert r.status_code == 201, r.text
    run = r.json()
    body = json.dumps(run["request_body"])
    for forbidden in ("2025-01-10", "ACC12345", "draw.csv", "SYA", "SYB", "Hemoglobin A1c", "sk-test"):
        assert forbidden not in body, forbidden
    for oid in run["local_refs"].values():
        assert oid not in body
    payload = json.loads(run["request_body"]["messages"][0]["content"].split("\n", 1)[1])
    assert [o["ref"] for o in payload["observations"]] == ["O1", "O2", "O3", "O4"]
    assert {o["timing"] for o in payload["observations"]} == {"draw 1 (day 0)"}
    assert payload["same_performing_laboratory_for_all_rows"] is False
    assert payload["consistency_check"][0]["use"].startswith("Consistency check only")
    assert {e["id"] for e in payload["evidence"]} >= {"epstein-2025-apob-vs-ldlp", "glavinovic-2022-apob-physiology"}
    assert run["request_body"]["model"] == "claude-opus-5-5" and run["request_body"]["max_tokens"] == live_run.MAX_TOKENS
    assert run["status"] == "awaiting_approval" and run["approval"] is None
    assert run["estimate"]["cost_usd_max"] > run["estimate"]["cost_usd_typical"] > 0
    assert any(d["setting"] == "Standard API retention" for d in run["data_handling"])


def test_approval_must_match_the_exact_request_and_is_single_use(client, configured, monkeypatch):
    _setup(client)
    _confirm_supporting(client)
    run = client.post("/api/v1/research/live-runs").json()
    monkeypatch.setattr(providers.AnthropicProvider, "send", _fake_send(configured, _good_output()))
    url = f"/api/v1/research/live-runs/{run['id']}/approve"
    assert client.post(url, json=_approval(run, payload_sha256="0" * 64)).status_code == 409
    assert client.post(url, json=_approval(run, model="claude-sonnet-5-5")).status_code == 409
    assert client.post(url, json=_approval(run, approve_this_payload_for_this_run_only=False)).status_code == 422
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-sonnet-5-5")  # configuration changed after preparation
    assert client.post(url, json=_approval(run)).status_code == 409
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-opus-5-5")
    assert configured == []  # nothing sent by any refused approval
    r = client.post(url, json=_approval(run))
    assert r.status_code == 202, r.text
    assert len(configured) == 1 and configured[0] == run["request_body"]  # exactly the approved request
    done = client.get(f"/api/v1/research/live-runs/{run['id']}").json()
    assert done["status"] == "succeeded" and done["response_model"] == "claude-opus-5-5"
    assert done["usage"]["output_tokens"] == 3000 and done["cost_usd"] == pytest.approx(9000 * 4e-6 + 3000 * 2e-5)
    assert done["approval"]["scope"] == "this run only" and done["snapshot_version"] >= 1
    assert done["citation_check"]["structurally_valid"] and done["citation_check"]["scope_flags"] == []
    assert client.post(url, json=_approval(run)).status_code == 409  # consumed
    assert len(configured) == 1


def test_failed_call_is_recorded_and_not_retried(client, configured, monkeypatch):
    _setup(client)
    _confirm_supporting(client)
    run = client.post("/api/v1/research/live-runs").json()
    calls = []
    monkeypatch.setattr(providers.AnthropicProvider, "send",
                        lambda self, body, t: calls.append(1) or providers.LiveResponse("failed", None, 5.0, "HTTP 401 authentication_error"))
    assert client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run)).status_code == 202
    done = client.get(f"/api/v1/research/live-runs/{run['id']}").json()
    assert done["status"] == "failed" and done["error"] == "HTTP 401 authentication_error" and calls == [1]


def test_recorded_request_and_approval_cannot_be_altered(client, configured):
    _setup(client)
    _confirm_supporting(client)
    run = client.post("/api/v1/research/live-runs").json()
    engine = create_engine(TEST_DB)
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("update research_live_runs set request_body = '{}' where id = :id"), {"id": run["id"]})
    with pytest.raises(Exception):
        with engine.begin() as conn:  # cannot start without an approval
            conn.execute(text("update research_live_runs set status = 'running' where id = :id"), {"id": run["id"]})
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("delete from research_live_runs where id = :id"), {"id": run["id"]})
    engine.dispose()
    assert client.post(f"/api/v1/research/live-runs/{run['id']}/withdraw").status_code == 200
    assert client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run)).status_code == 409


def test_split_name_on_the_investigation_draw_blocks_unrelated_ones_do_not(client, configured):
    extra = (b"LDL MEDIUM PARTICLE,310,nmol/L,2025-01-10,SYA,<215,H,,ACC12345\n"
             b"PARTICLE NUMBER CONTINUED,310,nmol/L,2025-01-10,SYA,<215,H,,ACC12345\n"
             b"ZINC RBC,12,mg/L,2024-03-01,SYB,,,,ACC99\n"
             b"ZN RBC FRAGMENT,12,mg/L,2024-03-01,SYB,,,,ACC99\n")
    doc = upload(client, "draw.csv", data=HEADER + DRAW + extra)
    client.post(f"/api/v1/documents/{doc['id']}/auto-accept")
    _confirm_supporting(client)
    ready = client.get("/api/v1/research/apob-ldlp/readiness").json()
    groups = ready["fragment_groups"]
    assert sorted(g["affects_investigation"] for g in groups) == [False, True]
    assert not next(g for g in ready["gates"] if g["id"] == "split_names")["ok"]


def test_citation_check_flags_unknown_refs_uncited_statements_and_scope():
    payload = {"observations": [{"ref": "O1"}], "evidence": [{"id": "rec", "claims": [{"ref": "rec/c1"}]}],
               "laboratory_documentation": [], "rules_based_interpretation": {"claims": [{"ref": "R1", "evidence_refs": []}],
                                                                              "hypotheses": [{"ref": "H1"}]}}
    s = _s
    out = {"input_issues": [], "established": [s("x", e=["rec/c9"]), s("y", r=["R1"])], "competing_explanations": [],
           "remaining_uncertainty": [s("z")], "distinguishing_information": [],
           "comparison_with_rules": {"differences_from_rules": [], "unchanged": [s("You should start a statin.", r=["R1"])]}}
    c = live_run.citation_check(payload, out)
    assert c["unknown_refs"] == [{"path": "established[0]", "ref": "rec/c9"}]
    assert c["established_without_observation_or_evidence"] == ["established[1]"]
    assert c["uncited"] == ["remaining_uncertainty[0]"]
    assert set(c["scope_flags"]) == {"recommendation", "treatment"} and not c["structurally_valid"]


def test_scrub_check_reports_categories_not_values():
    forbidden = {"accession": {"ACC12345"}, "document": {"report.pdf"}}
    assert live_run.scrub_violations("ok text", forbidden) == []
    assert live_run.scrub_violations("see ACC12345 on 2025-01-10", forbidden) == ["accession", "calendar_date"]


def test_output_schema_contains_no_personal_data_and_only_supported_keywords():
    blob = json.dumps(live_run.OUTPUT_SCHEMA)
    for kw in ("minimum", "maximum", "minLength", "maxLength", "pattern", "enum", "const"):
        assert f'"{kw}"' not in blob
    # The statement is defined once and referenced; inlining it overflowed the API's grammar limit.
    assert blob.count('"statement": {"type": "string"}') == 1


def test_rule_refs_alone_do_not_support_a_conclusion():
    payload = {"observations": [{"ref": "O1"}], "evidence": [], "laboratory_documentation": [],
               "rules_based_interpretation": {"claims": [{"ref": "R1", "evidence_refs": []}], "hypotheses": [{"ref": "H1"}]}}
    out = {"input_issues": [_s("H1 is stale.", r=["H1"])], "established": [], "remaining_uncertainty": [],
           "distinguishing_information": [], "comparison_with_rules": {"differences_from_rules": [], "unchanged": []},
           "competing_explanations": [{"explanation": "x", "relation_to_supplied": "keeps H1", "rule_refs": ["H1"],
                                       "supporting": [_s("Because R1 says so.", r=["R1"])], "contrary": [],
                                       "evidence_gaps": [_s("Nothing compares the assays.", r=["H1"])],
                                       "assessment": _s("Likely.", r=["H1"], inference=True)}]}
    c = live_run.citation_check(payload, out)
    # Input issues and evidence gaps may name only the rule under review; support and assessments may not.
    assert c["supported_only_by_rule_refs"] == ["competing_explanations[0].supporting[0]",
                                                "competing_explanations[0].assessment"]
    assert c["inferences"] == 1 and c["input_issues"] == 1 and not c["structurally_valid"]


def test_system_instruction_treats_rules_as_proposals():
    for phrase in ("proposals to evaluate, not as independent evidence", "Do not treat missing evidence as contrary",
                   "cannot by itself substantiate", "Do not equate laboratory reference-range disagreement"):
        assert phrase in live_run.SYSTEM
