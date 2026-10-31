"""Research partner on synthetic records: the cardiovascular overview, self-reported context, questions with
retrieval, explicitly accepted notes, investigations with versions, and preserved predictions.
No network: the provider's transport is replaced by a fake and literature search is off or faked."""

import json
import re

import pytest
from sqlalchemy import create_engine, text

from conftest import TEST_DB, upload

from app.research import live_run, partner, providers, retrieval

HEADER = b"Test,Result,Units,Collection Date,Lab,Reference Range,Flag,Method,Accession\n"
DRAW1 = (b"Apolipoprotein B,95,mg/dL,2023-03-02,SYA,<90,H,,ACC11111\n"
         b"LDL Cholesterol (direct),120,mg/dL,2023-03-02,SYA,<100,H,,ACC11111\n"
         b"Hemoglobin A1c,5.4,%,2023-03-02,SYA,<5.7,,,ACC11111\n")
DRAW2 = (b"LDL PARTICLE NUMBER,1500,nmol/L,2025-01-10,SYA,<1138,H,Ion Mobility,ACC12345\n"
         b"Apolipoprotein B,66,mg/dL,2025-01-10,SYB,<90,,,ACC12345\n"
         b"LDL Cholesterol (direct),80,mg/dL,2025-01-10,SYA,<100,,,ACC12345\n"
         b"LDL SMALL,240,nmol/L,2025-01-10,SYA,<142,H,Ion Mobility,ACC12345\n")
ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


@pytest.fixture
def configured(monkeypatch, tmp_path):
    key = tmp_path / "anthropic_api_key"
    key.write_text("sk-test-not-real\n")
    monkeypatch.setenv("CARDIO_RESEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("CARDIO_LLM_API_KEY_FILE", str(key))
    monkeypatch.delenv("CARDIO_LITERATURE_SEARCH", raising=False)
    monkeypatch.setattr(live_run, "start", lambda run_id: live_run.execute(run_id))
    sent: list[dict] = []
    return sent


def _send(monkeypatch, sent, output):
    def send(self, body, timeout_s):
        sent.append(body)
        return providers.LiveResponse("succeeded", {
            "id": "msg_test", "model": "claude-opus-5-5", "stop_reason": "end_turn",
            "usage": {"input_tokens": 5000, "output_tokens": 2000},
            "content": [{"type": "text", "text": json.dumps(output)}]}, 10.0)
    monkeypatch.setattr(providers.AnthropicProvider, "send", send)


def _s(t, o=(), c=(), e=(), p=(), inference=False):
    return {"statement": t, "is_inference": inference, "observation_refs": list(o), "context_refs": list(c),
            "evidence_refs": list(e), "prior_refs": list(p)}


def _answer(**over):
    return {"answer": "Two draws; blood pressure is unknown.", "established": [], "interpretations": [],
            "unknown": [_s("Blood pressure is not in the record.")], "would_change_understanding": [],
            "proposed_notes": [{"kind": "open_question", "text": "Is blood pressure normal?"}], **over}


def _investigation(**over):
    return {"summary": "Nothing unusual is established.", "conclusion_status": "nothing_unusual_established",
            "learned": [], "interpretation_changes": [], "contradictory_or_limiting_evidence": [], "applicability": [],
            "unresolved": [_s("Within-person variation is unknown.")], "distinguishing_information": [],
            "next_step": {"missing_history": [{"item": "Medication history", "why": "Changes between draws."}],
                          "collectable_observations": [{"observation": "Repeat ApoB", "why": "Third point."}],
                          "clinical_review_questions": [{"question": "Is treatment indicated?", "why": "Clinician."}]},
            "protocol": {"stage": "observation_period", "title": "Observe ApoB", "question": "Is ApoB stable?",
                         "hypothesis": "ApoB is stable within assay variation.", "outcome": "ApoB at the next draw",
                         "measurement_window": "The next draw after locking", "required_inputs": ["ApoB", "method"],
                         "comparison_baseline": "Mean of prior comparable values", "analysis_approach": "Absolute difference",
                         "counts_against_hypothesis": "A change larger than the documented assay variation",
                         "prediction": "Within assay variation of the baseline", "limitations": ["Biomarker, not health"],
                         "evidence_needed_before_intervention_prediction": ["A verified estimate of within-person variation"]},
            "proposed_notes": [], **over}


def _approval(run):
    return {k: run[k] for k in ("payload_sha256", "provider", "model", "endpoint")} | {"approve_this_payload_for_this_run_only": True}


def _records(client, confirm_all=False):
    for name, rows in (("d1.csv", DRAW1), ("d2.csv", DRAW2)):
        doc = upload(client, name, data=HEADER + rows)
        assert client.post(f"/api/v1/documents/{doc['id']}/auto-accept").status_code == 200
    if confirm_all:
        for d in client.get("/api/v1/research/overview").json()["domains"]:
            for s in d["series"]:
                for p in s["points"]:
                    if p["status"] == "software_checked":
                        assert client.post(f"/api/v1/observations/{p['observation_id']}/confirm",
                                           json={"confirm_source_matches": True}).status_code == 200


def _payload(run):
    return json.loads(run["request_body"]["messages"][0]["content"].split("\n", 1)[1])


# --- Overview ------------------------------------------------------------------------

def test_overview_is_organized_by_question_and_shows_unknown_domains(client):
    _records(client)
    ov = client.get("/api/v1/research/overview").json()
    doms = {d["id"]: d for d in ov["domains"]}
    assert doms["lipids"]["state"] == "measured"
    assert doms["blood_pressure"]["state"] == "unknown"
    assert doms["family_history"]["state"] == "unknown"
    assert doms["kidney"]["state"] == "unknown"
    assert any("Unknown, not normal" in c for c in doms["blood_pressure"]["cannot_establish"])
    # particle measures sit in the lipid question, not as a separate PDF section
    labels = {s["label"] for s in doms["lipids"]["series"]}
    assert {"ApoB", "LDL-C", "LDL PARTICLE NUMBER"} <= labels
    # old measurements are not current; a lab flag is not a risk assessment
    assert any("more than a year old" in c for c in doms["lipids"]["cannot_establish"])
    assert any("not an assessment of cardiovascular risk" in c for c in ov["headline"]["cannot_establish"])
    assert any("PREVENT" in c and "systolic blood pressure" in c for c in ov["headline"]["cannot_establish"])
    assert ov["headline"]["deserves_investigation"]


def test_overview_keeps_statuses_apart_and_unresolved_items_do_not_block(client):
    _records(client)
    # a third document left unreviewed: visible as awaiting review, lipids still measured
    upload(client, "d3.csv", data=HEADER + b"Creatinine,0.9,mg/dL,2025-06-01,SYA,0.6-1.3,,,ACC22222\n")
    ov = client.get("/api/v1/research/overview").json()
    doms = {d["id"]: d for d in ov["domains"]}
    assert doms["kidney"]["state"] == "awaiting_review"
    assert doms["kidney"]["awaiting_review"] == 1
    assert doms["lipids"]["state"] == "measured"
    statuses = {p["status"] for s in doms["lipids"]["series"] for p in s["points"]}
    assert statuses == {"software_checked"}
    assert ov["counts"]["awaiting_review"] == 1


def test_series_change_is_only_between_comparable_points(client):
    _records(client)
    lipids = next(d for d in client.get("/api/v1/research/overview").json()["domains"] if d["id"] == "lipids")
    ldl = next(s for s in lipids["series"] if s["label"] == "LDL-C")
    assert ldl["change"]["draws"] == 2 and ldl["change"]["difference"] == -40
    apob = [s for s in lipids["series"] if s["label"] == "ApoB"]
    assert any("laboratory codes differ" in n for s in apob for n in s["comparability"])


# --- Context -------------------------------------------------------------------------

def test_context_is_append_only_and_supersession_keeps_history(client):
    r = client.post("/api/v1/context", json={"domain": "blood_pressure", "item": "Blood pressure reading (systolic/diastolic, mmHg)",
                                             "value_text": "128/82", "as_of": "2025-02-01"})
    assert r.status_code == 201
    first = r.json()["id"]
    r = client.post("/api/v1/context", json={"domain": "blood_pressure", "item": "Blood pressure reading (systolic/diastolic, mmHg)",
                                             "value_text": "122/80", "as_of": "2025-03-01", "supersedes_id": first})
    assert r.status_code == 201
    entries = client.get("/api/v1/context").json()["entries"]
    assert [e["current"] for e in entries] == [False, True]
    assert client.post("/api/v1/context", json={"domain": "blood_pressure", "item": "x", "value_text": "y",
                                                "supersedes_id": first}).status_code == 409
    eng = create_engine(TEST_DB)
    with pytest.raises(Exception, match="not permitted"), eng.begin() as conn:
        conn.execute(text("UPDATE participant_context SET value_text = 'changed'"))
    eng.dispose()
    bp = next(d for d in client.get("/api/v1/research/overview").json()["domains"] if d["id"] == "blood_pressure")
    assert bp["state"] == "self_reported" and len(bp["context"]) == 1


# --- Questions -----------------------------------------------------------------------

def test_question_retrieves_relevant_records_and_payload_is_scrubbed(client, configured, monkeypatch):
    _records(client)
    upload(client, "d3.csv", data=HEADER + b"Apolipoprotein B,70,mg/dL,2025-06-01,SYA,<90,,,ACC22222\n")  # unreviewed
    client.post("/api/v1/context", json={"domain": "family_history", "item": "Premature cardiovascular disease in a first-degree relative",
                                         "value_text": "Father, heart attack at 52", "as_of": "2024-01-01"})
    r = client.post("/api/v1/research/questions", json={"text": "What do my LDL results show?"})
    assert r.status_code == 201, r.text
    run = r.json()["run"]
    assert run["kind"] == "conversation" and run["status"] == "awaiting_approval"
    assert run["context"]["retrieval"]["domains"] == ["lipids"]
    payload = _payload(run)
    assert {o["domain"] for o in payload["observations"]} == {"lipids"}
    assert payload["record_scope"]["rows_awaiting_review_not_sent"] == 1
    assert payload["self_reported_context"] == []  # family history is not a lipid domain
    body = json.dumps(run["request_body"])
    assert not ISO.search(body)
    for bad in ("ACC11111", "ACC12345", "SYA", "SYB", "d1.csv", "d2.csv"):
        assert bad not in body
    assert all(o["id"] not in body for o in client.get("/api/v1/observations").json())

    # a whole-record question retrieves every domain, including self-reported context
    r = client.post("/api/v1/research/questions", json={"text": "What does my history establish about my cardiovascular risk, "
                                                                "and what remains unknown?", "conversation_id": r.json()["conversation_id"]})
    payload = _payload(r.json()["run"])
    assert len(payload["record_scope"]["domains_included"]) == len(partner.DOMAINS)
    assert payload["self_reported_context"][0]["status"].startswith("self-reported")
    assert "blood_pressure" in payload["record_scope"]["domains_with_no_information"]


def test_answer_is_cited_and_established_on_unconfirmed_is_flagged(client, configured, monkeypatch):
    _records(client)
    run = client.post("/api/v1/research/questions", json={"text": "What do my lipids show?"}).json()["run"]
    refs = {o["ref"] for o in _payload(run)["observations"]}
    o1 = sorted(refs)[0]
    _send(monkeypatch, configured, _answer(established=[_s("LDL-C was measured twice.", o=[o1])],
                                           interpretations=[_s("Uncited inference.", inference=True)]))
    r = client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    assert r.status_code == 202, r.text
    done = client.get(f"/api/v1/research/runs/{run['id']}").json()
    assert done["status"] == "succeeded" and len(configured) == 1
    check = done["citation_check"]
    assert check["established_on_unconfirmed_observations"] == ["established[0]"]
    assert check["uncited"] == ["interpretations[0]", "unknown[0]"]
    assert not check["structurally_valid"]
    assert done["refs"][o1]["kind"] == "observation"
    # the conversation shows the question, the records used and the answer
    conv = client.get(f"/api/v1/research/conversations/{done['context']['conversation_id']}").json()
    assert conv["turns"][0]["used"] and conv["turns"][0]["run"]["output"]["answer"]
    # approval stays single use
    assert client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run)).status_code == 409


def test_flagged_prior_finding_is_not_presented_as_accepted(client, configured, monkeypatch):
    _records(client, confirm_all=True)
    from test_live_run import _good_output

    out = _good_output()
    out["established"].append({"statement": "Uncited established claim.", "is_inference": False,
                               "observation_refs": [], "evidence_refs": [], "rule_refs": []})
    _send(monkeypatch, configured, out)
    prep = client.post("/api/v1/research/live-runs")
    assert prep.status_code == 201, prep.text
    apob = prep.json()
    assert client.post(f"/api/v1/research/live-runs/{apob['id']}/approve", json=_approval(apob)).status_code == 202
    lipids = next(d for d in client.get("/api/v1/research/overview").json()["domains"] if d["id"] == "lipids")
    stmts = lipids["interpretations"][0]["statements"]
    assert [s["accepted"] for s in stmts] == [True, False]
    assert stmts[1]["flag"]
    run = client.post("/api/v1/research/questions", json={"text": "What about my ApoB?"}).json()["run"]
    prior = _payload(run)["prior_findings"]
    assert [p["status"].startswith("FLAGGED") for p in prior] == [False, True]
    # established statements resting on a flagged prior finding fail the check
    flagged_ref = prior[1]["ref"]
    _send(monkeypatch, configured, _answer(established=[_s("Restated.", e=["epstein-2025-apob-vs-ldlp"], p=[flagged_ref])]))
    client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    check = client.get(f"/api/v1/research/runs/{run['id']}").json()["citation_check"]
    assert check["established_on_flagged_prior"] == ["established[0]"]


# --- Notes ---------------------------------------------------------------------------

def test_notes_exist_only_when_accepted_and_reach_later_requests(client, configured, monkeypatch):
    _records(client)
    run = client.post("/api/v1/research/questions", json={"text": "What do my lipids show?"}).json()["run"]
    _send(monkeypatch, configured, _answer())
    client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    assert client.get("/api/v1/research/notes").json() == []  # a proposed note is not saved by itself
    n = client.post("/api/v1/research/notes", json={"kind": "working_hypothesis", "text": "LDL-C fell between draws.",
                                                    "source_run_id": run["id"]}).json()
    run2 = client.post("/api/v1/research/questions", json={"text": "Did my LDL change?"}).json()["run"]
    notes = _payload(run2)["accepted_notes"]
    assert notes[0]["text"] == "LDL-C fell between draws." and "not evidence" in notes[0]["status"]
    assert client.post(f"/api/v1/research/notes/{n['id']}/withdraw").status_code == 200
    run3 = client.post("/api/v1/research/questions", json={"text": "Did my LDL change?"}).json()["run"]
    assert _payload(run3)["accepted_notes"] == []
    eng = create_engine(TEST_DB)
    with pytest.raises(Exception, match="only be withdrawn"), eng.begin() as conn:
        conn.execute(text("UPDATE research_notes SET text = 'a fact now'"))
    eng.dispose()


# --- Investigations, versions and new information --------------------------------------

def test_priorities_are_at_most_three_and_explain_themselves(client):
    _records(client)
    prios = client.get("/api/v1/research/priorities").json()
    assert 1 <= len(prios) <= 3
    assert [p["id"] for p in prios] == ["lipid-exposure", "missing-major-context", "particle-discordance"]
    for p in prios:
        assert p["relevance"] and p["uncertain"] and p["could_change"]
        assert not any(k in p for k in ("score", "importance"))
    assert "not because an unusual result is important" in prios[2]["relevance"]


def test_literature_queries_are_constant_and_non_identifying():
    for queries in partner.PRIORITY_QUERIES.values():
        for q in queries.values():
            assert not re.search(r"\d", q)
    assert retrieval.search_literature(partner.PRIORITY_QUERIES["lipid-exposure"], env={})["status"] == "off"


def test_investigation_versions_and_new_information(client, configured, monkeypatch):
    _records(client)
    monkeypatch.setattr(partner, "literature_search", lambda pid, env=None: {
        "status": "live", "queries": list(partner.PRIORITY_QUERIES[pid].values()),
        "candidates": [{"pmid": "123456", "title": "A synthetic abstract", "journal": "J", "year": "2020",
                        "abstract": "Synthetic text.", "status": "abstract only"}]})
    r = client.post("/api/v1/research/investigations", json={"priority_id": "lipid-exposure"})
    assert r.status_code == 201, r.text
    inv_id, run = r.json()["investigation_id"], r.json()["run"]
    payload = _payload(run)
    assert payload["literature_candidates"][0]["pmid"] == "123456"
    assert run["context"]["search"]["pmids"] == ["123456"]
    _send(monkeypatch, configured, _investigation(learned=[_s("ApoB measured on two dates.", e=["pmid:123456"])]))
    client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    inv = client.get(f"/api/v1/research/investigations/{inv_id}").json()
    assert inv["new_information"]["any"] is False
    assert inv["runs"][0]["citation_check"]["unknown_refs"] == []
    assert inv["runs"][0]["refs"]["pmid:123456"]["url"].endswith("/123456/")

    # new information arrives: the investigation says so; a new version keeps the earlier one
    client.post("/api/v1/context", json={"domain": "medications", "item": "Lipid-lowering medication", "value_text": "None"})
    inv = client.get(f"/api/v1/research/investigations/{inv_id}").json()
    assert inv["new_information"]["any"] and len(inv["new_information"]["context_added"]) == 1
    run2 = client.post("/api/v1/research/investigations", json={"priority_id": "lipid-exposure"}).json()["run"]
    assert run2["context"]["version"] == 2
    prev = _payload(run2)["previous_version_of_this_investigation"]
    assert prev["summary"] == "Nothing unusual is established." and "not evidence" in prev["status"]
    _send(monkeypatch, configured, _investigation(summary="Unchanged; medication history now known.", interpretation_changes=[
        {"previous": "Medication unknown", "current": "No lipid-lowering medication reported", "why": _s("Reported.", c=["C1"])}]))
    client.post(f"/api/v1/research/live-runs/{run2['id']}/approve", json=_approval(run2))
    inv = client.get(f"/api/v1/research/investigations/{inv_id}").json()
    assert [r["output"]["summary"] for r in inv["runs"]] == ["Nothing unusual is established.",
                                                             "Unchanged; medication history now known."]
    assert inv["new_information"]["any"] is False


# --- Next investigation and predictions -------------------------------------------------

def test_next_view_and_prediction_lifecycle(client, configured, monkeypatch):
    _records(client)
    nxt = client.get("/api/v1/research/next").json()
    assert nxt["source"] == "static" and nxt["protocol"] is None and nxt["next_step"]["missing_history"]
    run = client.post("/api/v1/research/investigations", json={"priority_id": "lipid-exposure"}).json()["run"]
    _send(monkeypatch, configured, _investigation())
    client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    nxt = client.get("/api/v1/research/next").json()
    assert nxt["source"] == "investigation" and nxt["protocol"]["stage"] == "observation_period"

    p = client.post("/api/v1/research/predictions", json={"source_run_id": run["id"]}).json()
    assert p["status"] == "draft"
    res = {"result_text": "ApoB 70", "assessment": "inconclusive"}
    assert client.post(f"/api/v1/research/predictions/{p['id']}/results", json=res).status_code == 409
    locked = client.post(f"/api/v1/research/predictions/{p['id']}/lock").json()
    assert locked["status"] == "locked" and len(locked["protocol_sha256"]) == 64
    eng = create_engine(TEST_DB)
    with pytest.raises(Exception, match="locked"), eng.begin() as conn:
        conn.execute(text("UPDATE research_predictions SET protocol = '{}'::jsonb"))
    eng.dispose()
    # an observation collected before the lock is not a prospective outcome
    old = next(o for o in client.get("/api/v1/observations").json() if o["collection_date"])
    r = client.post(f"/api/v1/research/predictions/{p['id']}/results", json=res | {"observation_ids": [old["id"]]})
    assert r.status_code == 409
    r = client.post(f"/api/v1/research/predictions/{p['id']}/results", json=res)
    assert r.status_code == 201 and len(r.json()["results"]) == 1


def test_missing_key_blocks_and_fake_provider_is_labelled(client, monkeypatch, tmp_path):
    monkeypatch.setenv("CARDIO_RESEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("CARDIO_LLM_API_KEY_FILE", str(tmp_path / "missing"))
    monkeypatch.setenv("CARDIO_LLM_MODEL", "claude-opus-5-5")
    assert any("No API key" in b for b in providers.live_provider().blockers())
    _records(client)
    run = client.post("/api/v1/research/questions", json={"text": "What do my lipids show?"}).json()["run"]
    r = client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run))
    assert r.status_code == 409 and "not ready" in r.json()["detail"]
    monkeypatch.setenv("CARDIO_RESEARCH_PROVIDER", "fake")
    monkeypatch.setattr(live_run, "start", lambda run_id: live_run.execute(run_id))
    run = client.post("/api/v1/research/questions", json={"text": "What do my lipids show?"}).json()["run"]
    assert run["provider"] == "fake" and run["estimate"]["cost_usd_max"] == 0
    assert client.post(f"/api/v1/research/live-runs/{run['id']}/approve", json=_approval(run)).status_code == 202
    done = client.get(f"/api/v1/research/runs/{run['id']}").json()
    assert done["status"] == "succeeded" and done["output"]["answer"].startswith(providers.FAKE_MARK)
