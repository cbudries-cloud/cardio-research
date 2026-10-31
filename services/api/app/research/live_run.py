"""One live, evidence-linked run of the ApoB / LDL-P investigation.

prepare -> (participant reads the exact request on the approval screen) -> approve -> one call.

- Inputs come only from a research snapshot taken at preparation time, and only from observations
  the participant confirmed against their source (verification_method participant_review). The run
  is refused while any observation the investigation depends on is unconfirmed, or while a
  possible split test name on the same draw could belong to its inputs.
- The outgoing payload carries no name, birth date, address, accession number, document name or
  path, record ID, laboratory code or calendar date, and no measurement the investigation does not
  use. Timing is relative ("draw 1, day 0"). A scrub check against every such value in the snapshot
  refuses preparation if anything leaks. The remaining health data is not anonymous.
- Approval is a record on this run, bound to the payload hash, provider, model and endpoint. It is
  consumed by the run and never applies to another run, provider, model, data scope or schedule.
- The response is stored only in the database; logs and audit events carry status and token
  counts, never content.
"""

import hashlib
import json
import math
import re
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.logging_safe import log_exception_without_message
from app.models import Participant, ResearchLiveRun, ResearchSnapshot, SourceDocument
from app.research import discrepancy, providers, runtime
from app.services import records
from app.services.records import DomainError

INVESTIGATION = "apob-ldlp-v0.2"
MAX_TOKENS = 24000  # hard cap on output, thinking included
EFFORT = "high"
TIMEOUT_S = 300
CHARS_PER_TOKEN_LOWER_BOUND = 2.0  # docs: ~2.5 characters per token on the current tokenizer; 2.0 over-estimates
TYPICAL_OUTPUT_TOKENS = 8000
ROLE_ORDER = {"LDL particle number": 0, "ApoB": 1, "LDL-C": 2, "LDL subfraction": 3}
FRAGMENT_TERMS = re.compile(r"ldl|apo|particle|lipoprotein|hdl|pattern|peak|small|medium|large", re.I)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

SYSTEM = """You assist one person who is studying their own laboratory records for research. You receive a JSON \
payload: a fixed research question, observations the person confirmed against their source reports (identified as \
O1, O2, ...; timing is relative), a deterministic consistency check, the application's existing rules-based \
interpretation (claims R1, R2, ... and hypotheses H1, H2, ...), and evidence records with verbatim quotes \
(cite as <record-id>/<claim-id>, <record-id>, or lab-doc:<id>). No tools are available: this is a review of the \
supplied material only.

How to treat the inputs:
- Treat rules_based_interpretation, the supplied hypotheses, and the interpretation fields of evidence records as \
proposals to evaluate, not as independent evidence.
- Before interpreting the observations, identify internal contradictions, unsupported inferences, stale verification \
states and missing source support in the payload. Report them in input_issues.
- You may reject, revise, combine or add explanations when the supplied observations and source material support \
doing so. Say in relation_to_supplied which hypothesis an explanation keeps, revises, combines or replaces, or that \
it is new.
- A rule reference identifies the claim being reviewed. It cannot by itself substantiate a factual conclusion; \
cite the observations or evidence the conclusion rests on.
- Distinguish source-supported statements from your own inferences: set is_inference to true for an inference, cite \
its premises and state its limitations in the statement.
- Do not equate laboratory reference-range disagreement (flags), particle-count consistency (the consistency check) \
and cohort-defined statistical discordance (a study's regression line). They are different comparisons.
- Do not treat missing evidence as contrary evidence. Report evidence gaps explicitly in evidence_gaps or \
remaining_uncertainty. Do not fill them with uncited background knowledge, and do not force a novel finding.

Produce the JSON object the output schema describes:
- input_issues: problems found in the payload itself (empty if none).
- established: what these observations establish, and only that.
- competing_explanations: each explanation with supporting and contrary items, evidence gaps, and an assessment \
that cites what it rests on.
- remaining_uncertainty: what stays unknown.
- distinguishing_information: information that could distinguish the explanations, described as information, not \
as an instruction to obtain it.
- comparison_with_rules: differences_from_rules (what this review changes relative to the rules-based \
interpretation; empty if nothing defensible changes) and unchanged.

Rules:
- Cite only refs present in the payload. If a statement rests on no ref, put it in remaining_uncertainty and say so.
- Do not add numbers that are not in the payload.
- The consistency check is not evidence that either test is wrong; do not use it to reject an observation or to \
decide which test is correct.
- Do not estimate personal risk, diagnose, recommend tests, treatments, medication or lifestyle changes, or suggest \
publishing anything. Group results from studies are not this person's risk.
- Plain technical English."""

_STATEMENT = {
    "type": "object", "additionalProperties": False,
    "required": ["statement", "is_inference", "observation_refs", "evidence_refs", "rule_refs"],
    "properties": {"statement": {"type": "string"}, "is_inference": {"type": "boolean"},
                   "observation_refs": {"type": "array", "items": {"type": "string"}},
                   "evidence_refs": {"type": "array", "items": {"type": "string"}},
                   "rule_refs": {"type": "array", "items": {"type": "string"}}},
}
# The statement is referenced through $defs: inlining it at every use exceeded the API's compiled-grammar
# limit (HTTP 400 on the first live run, 2026-10-26).
_REF = {"$ref": "#/$defs/statement"}
_LIST = {"type": "array", "items": _REF}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "$defs": {"statement": _STATEMENT},
    "required": ["input_issues", "established", "competing_explanations", "remaining_uncertainty",
                 "distinguishing_information", "comparison_with_rules"],
    "properties": {
        "input_issues": _LIST,
        "established": _LIST,
        "competing_explanations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["explanation", "relation_to_supplied", "rule_refs", "supporting", "contrary", "evidence_gaps",
                         "assessment"],
            "properties": {"explanation": {"type": "string"}, "relation_to_supplied": {"type": "string"},
                           "rule_refs": {"type": "array", "items": {"type": "string"}},
                           "supporting": _LIST, "contrary": _LIST, "evidence_gaps": _LIST, "assessment": _REF}}},
        "remaining_uncertainty": _LIST,
        "distinguishing_information": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["information", "explanations_distinguished", "evidence_refs"],
            "properties": {"information": {"type": "string"},
                           "explanations_distinguished": {"type": "array", "items": {"type": "string"}},
                           "evidence_refs": {"type": "array", "items": {"type": "string"}}}}},
        "comparison_with_rules": {
            "type": "object", "additionalProperties": False, "required": ["differences_from_rules", "unchanged"],
            "properties": {"differences_from_rules": _LIST, "unchanged": _LIST}},
    },
}
SCOPE_PATTERNS = {
    "recommendation": r"\byou should\b|\brecommend|\bconsider (taking|starting|asking)",
    "test_ordering": r"\border(ing)? (a|an|another|the) .*test|\bget (a|an|another) .*test",
    "treatment": r"\b(start|stop|increase|decrease|begin)\w* (a |the |your )?(statin|medication|treatment|therapy|dose|supplement)",
    "diagnosis": r"\bdiagnos(is|e|ed)\b",
    "personal_risk": r"\byour (personal |own )?risk (is|of)\b|\byou (are|have) (at )?(high|low|elevated|increased) risk",
}


# --- Readiness -----------------------------------------------------------------------

def _supporting_ids(res: dict) -> set[str]:
    ids = {x["observation_id"] for x in res["q1_extraction"]}
    ids |= {i for c in res["claims"] for i in c["depends_on_observations"]}
    ids |= {i for h in res["hypotheses"] for i in h["depends_on_observations"]}
    return ids


def _fragment_groups(inputs: dict, draw_dates: set[str]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in inputs["observations"]:
        if not r["recognized"] and r["value"] is not None:
            groups.setdefault((r["collection_date"], r["value"], r["unit"]), []).append(r)
    out = []
    for g in groups.values():
        if len({r["test_as_written"].strip().upper() for r in g}) < 2:
            continue
        affects = g[0]["collection_date"] in draw_dates and any(FRAGMENT_TERMS.search(r["test_as_written"]) for r in g)
        out.append({"observation_ids": [r["observation_id"] for r in g], "affects_investigation": affects})
    return out


def readiness(session: Session, participant_id: uuid.UUID, env: dict | None = None) -> dict[str, Any]:
    inputs = runtime.build_inputs(session, participant_id)
    ledger = runtime.load_ledger()
    res = discrepancy.investigate_discrepancy(inputs["observations"], ledger, discrepancy.load_lab_docs(runtime.EVIDENCE_ROOT))
    provider = providers.live_provider(env)
    prov = {"name": provider.name if provider else None, "model": provider.model if provider else None,
            "endpoint": provider.endpoint if provider else None,
            "key_configured": bool(provider and provider.key_configured()),
            "blockers": provider.blockers() if provider else ["CARDIO_RESEARCH_PROVIDER names no live adapter"]}
    if res is None:
        return {"investigation": INVESTIGATION, "available": False, "supporting": [], "fragment_groups": [],
                "gates": [{"id": "inputs", "ok": False, "detail": "No current LDL particle number is among accepted observations."}],
                "provider": prov, "ready_to_prepare": False}
    by_id = {r["observation_id"]: r for r in inputs["observations"]}
    roles = {x["observation_id"]: x["role"] for x in res["q1_extraction"]}
    supporting = sorted(({"observation_id": i, "role": roles.get(i, "LDL subfraction"),
                          "verification_method": by_id[i]["verification_method"]} for i in _supporting_ids(res)),
                        key=lambda x: (ROLE_ORDER.get(x["role"], 9), x["observation_id"]))
    draw_dates = {by_id[x["observation_id"]]["collection_date"] for x in supporting}
    fragments = _fragment_groups(inputs, draw_dates)
    unconfirmed = sum(1 for x in supporting if x["verification_method"] != "participant_review")
    affecting = sum(1 for f in fragments if f["affects_investigation"])
    gates = [
        {"id": "sources_confirmed", "ok": unconfirmed == 0,
         "detail": f"{len(supporting) - unconfirmed} of {len(supporting)} supporting observations confirmed by you against the source."},
        {"id": "split_names", "ok": affecting == 0,
         "detail": f"{affecting} possible split test name group(s) on the investigation's draw could belong to its inputs; "
                   f"{len(fragments) - affecting} other group(s) stay unresolved and do not block this run."},
    ]
    return {"investigation": INVESTIGATION, "available": True, "supporting": supporting, "fragment_groups": fragments,
            "gates": gates, "provider": prov, "ready_to_prepare": all(g["ok"] for g in gates)}


# --- Payload -------------------------------------------------------------------------

def _forbidden_values(inputs: dict, participant_label: str | None, docs: dict[str, str]) -> dict[str, set[str]]:
    rows = inputs["observations"] + inputs.get("review_candidates", [])
    f: dict[str, set[str]] = {"date": set(), "accession": set(), "document": set(), "record_id": set(),
                              "laboratory_code": set(), "participant_label": set()}
    for r in rows:
        f["record_id"].add(r["observation_id"])
        if r.get("collection_date"):
            f["date"].add(r["collection_date"])
        if r.get("accession"):
            f["accession"].add(r["accession"])
        if r.get("laboratory"):
            f["laboratory_code"].add(r["laboratory"])
        src = r.get("source") or {}
        if src.get("document_id"):
            f["record_id"].add(src["document_id"])
        if src.get("document"):
            f["document"].add(src["document"])
    f["document"] |= set(docs.values())
    if participant_label:
        f["participant_label"].add(participant_label)
    return f


def scrub_violations(text: str, forbidden: dict[str, set[str]]) -> list[str]:
    """Categories of identifying values found in the outgoing text (never the values)."""
    found = []
    if ISO_DATE.search(text):
        found.append("calendar_date")
    for cat, values in forbidden.items():
        for v in values:
            v = (v or "").strip()
            if len(v) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(v)}(?![A-Za-z0-9])", text):
                found.append(cat)
                break
    return sorted(set(found))


def _ledger_extract(rec: dict) -> dict:
    c = rec["citation"]
    return {
        "id": rec["id"], "title": c["title"], "journal": c.get("journal"), "year": c.get("year"), "doi": c.get("doi"),
        "access": "full text reviewed" if rec["access"]["full_text_reviewed"] else "abstract only",
        "design": rec["study"]["design"], "population": rec["study"]["population"],
        "sample_size": rec["study"]["sample_size"],
        "claims": [{k: v for k, v in {
            "ref": f"{rec['id']}/{cl['id']}", "statement": cl["statement"], "value": cl.get("value"),
            "lower": cl.get("lower"), "upper": cl.get("upper"), "unit": cl["unit"], "measure": cl["measure"],
            "quote": (cl.get("source_location") or {}).get("quote")}.items() if v is not None} for cl in rec["claims"]],
        "limitations": [lim["text"] for lim in rec["limitations"]],
        "applicability_constraints": rec["applicability_constraints"],
        "interpretation": rec.get("interpretation"),
    }


def build_payload(snapshot_inputs: dict, res: dict, ledger: dict, lab_docs: dict) -> tuple[dict, dict[str, str]]:
    """(payload, local refs -> observation IDs). `res` is the verified investigation of the snapshot."""
    by_id = {r["observation_id"]: r for r in snapshot_inputs["observations"]}
    roles = {x["observation_id"]: x["role"] for x in res["q1_extraction"]}
    ids = sorted(_supporting_ids(res), key=lambda i: (ROLE_ORDER.get(roles.get(i, "LDL subfraction"), 9),
                                                      by_id[i]["collection_date"], by_id[i]["test_as_written"]))
    ref = {i: f"O{n}" for n, i in enumerate(ids, 1)}
    dates = sorted({by_id[i]["collection_date"] for i in ids})
    day0 = date.fromisoformat(dates[0])
    draw = {d: f"draw {n} (day {(date.fromisoformat(d) - day0).days})" for n, d in enumerate(dates, 1)}

    def obs(i: str) -> dict:
        r = by_id[i]
        return {k: v for k, v in {
            "ref": ref[i], "role": roles.get(i, "LDL subfraction"), "test_as_written": r["test_as_written"],
            "value_as_written": r["value_as_written"], "comparator": r["comparator"], "unit": r["unit"],
            "result_type": r["result_type"], "reference_range_as_printed": r["reference_range"],
            "lab_flag_as_printed": r["lab_flag"], "method_named_in_report": discrepancy.method_of(r)["method"],
            "specimen_type": r["specimen_type"], "timing": draw[r["collection_date"]],
            "verification": "confirmed by the participant against the source report"}.items() if v is not None}

    def refs(xs: list[str]) -> list[str]:
        return [ref[x] for x in xs if x in ref]

    q1 = {x["observation_id"]: x for x in res["q1_extraction"]}
    labs = {q1[i]["laboratory_code"] for i in q1 if q1[i]["laboratory_code"]}
    rule_claims = [c for c in res["claims"] if c["kind"] != "extraction"]
    rules = {f"R{n}": c for n, c in enumerate(rule_claims, 1)}
    hyps = {f"H{n}": h for n, h in enumerate(res["hypotheses"], 1)}
    lab_doc = lab_docs.get(discrepancy.LAB_DOC)
    payload = {
        "question": res["question"],
        "observations": [obs(i) for i in ids],
        "same_performing_laboratory_for_all_rows": len(labs) <= 1,
        "consistency_check": [{
            **{k: c[k] for k in ("expectation", "outcome", "use", "limitations")},
            "inputs": {role: {"ref": ref.get(v["observation_id"]), "value": v["value"], "unit": v["unit"],
                              "method_stated": v["method_stated"]} for role, v in c["inputs"].items()},
            "assumptions": [{k: a[k] for k in ("label", "nmol_per_l_per_mg_per_dl", "derivation", "evidence",
                                                "apob_particles_nmol_per_l", "ldlp_to_apob_particle_ratio")}
                            for a in c["assumptions"]]} for c in res.get("consistency_checks", [])],
        "rules_based_interpretation": {
            "status": "Proposals to evaluate, produced by deterministic rules in this application. Not evidence.",
            "claims": [{"ref": k, "kind": c["kind"], "text": c["text"], "observation_refs": refs(c["depends_on_observations"]),
                        "evidence_refs": c["depends_on_evidence"]} for k, c in rules.items()],
            "hypotheses": [{"ref": k, "hypothesis": h["hypothesis"], "supporting": h["supporting"],
                            "contrary": h["contrary"], "evidence_gaps": h.get("evidence_gaps", []),
                            "assumptions": h["assumptions"],
                            "distinguishing": h["distinguishing"], "observation_refs": refs(h["depends_on_observations"])}
                           for k, h in hyps.items()],
            "limitations": res["limitations"],
        },
        "evidence": [_ledger_extract(ledger[e["record"]]) for e in res["evidence"]],
        "laboratory_documentation": ([{"ref": f"lab-doc:{lab_doc['id']}",
                                       **{k: lab_doc[k] for k in ("laboratory", "test", "test_code", "url", "statements") if k in lab_doc}}]
                                     if lab_doc else []),
    }
    return payload, {v: k for k, v in ref.items()}


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare(session: Session, participant_id: uuid.UUID, env: dict | None = None) -> ResearchLiveRun:
    ready = readiness(session, participant_id, env)
    if not ready["ready_to_prepare"]:
        raise DomainError(409, "The investigation is not ready for a live run.", {"gates": ready["gates"]})
    provider = providers.live_provider(env)
    if provider is None or not provider.model:
        raise DomainError(409, "No live provider and model are configured.", {"blockers": ready["provider"]["blockers"]})
    snap = runtime.create_snapshot(session, participant_id)
    res = (snap.outputs.get("research_v02") or {}).get("verified")
    preview = (snap.outputs.get("research_v02") or {}).get("provisional_preview")
    if res is None or preview is None or _supporting_ids(res) != _supporting_ids(preview):
        raise DomainError(409, "The confirmed snapshot does not cover every observation the investigation uses.")
    ledger = runtime.load_ledger()
    payload, local_refs = build_payload(snap.inputs, res, ledger, discrepancy.load_lab_docs(runtime.EVIDENCE_ROOT))
    user_content = "Investigation payload (JSON):\n" + json.dumps(payload, indent=1, ensure_ascii=False)
    body = provider.build_request(system=SYSTEM, user_content=user_content, output_schema=OUTPUT_SCHEMA,
                                  max_tokens=MAX_TOKENS, effort=EFFORT)
    label = session.get(Participant, participant_id).label
    docs = {str(d.id): d.original_filename for d in session.scalars(
        select(SourceDocument).where(SourceDocument.participant_id == participant_id))}
    leaked = scrub_violations(json.dumps(body, ensure_ascii=False), _forbidden_values(snap.inputs, label, docs))
    if leaked:
        raise DomainError(409, "The outgoing payload contains identifying values; the run was not prepared.",
                          {"categories": leaked})
    prices = provider.prices() or {}
    est_in = math.ceil(len(json.dumps(body, ensure_ascii=False)) / CHARS_PER_TOKEN_LOWER_BOUND)
    cost = lambda out_tokens: round(est_in * prices.get("input", 0) / 1e6 + out_tokens * prices.get("output", 0) / 1e6, 4)
    run = ResearchLiveRun(
        id=uuid.uuid4(), participant_id=participant_id, snapshot_id=snap.id, status="awaiting_approval",
        provider=provider.name, model=provider.model, endpoint=provider.endpoint, request_body=body,
        payload_sha256=_sha(body), local_refs=local_refs, evidence_ids=[e["record"] for e in res["evidence"]],
        estimate={"input_tokens_upper_estimate": est_in, "max_output_tokens": MAX_TOKENS,
                  "typical_output_tokens": TYPICAL_OUTPUT_TOKENS, "price_usd_per_mtok": prices,
                  "cost_usd_typical": cost(TYPICAL_OUTPUT_TOKENS), "cost_usd_max": cost(MAX_TOKENS),
                  "basis": f"input tokens over-estimated at {CHARS_PER_TOKEN_LOWER_BOUND} characters per token of the "
                           "request body; output capped by max_tokens (thinking included). Maximum = estimated input "
                           "tokens x input price + max_tokens x output price, computed for this exact request. Prices from "
                           "platform.claude.com/docs/en/about-claude/pricing, retrieved 2026-10-26."},
        limits={"calls": 1, "retries": 0, "max_tokens": MAX_TOKENS, "effort": EFFORT, "timeout_seconds": TIMEOUT_S,
                "tools": "none", "streaming": False, "schedule": "none: runs once, only when you approve it"},
        data_handling=providers.ANTHROPIC_DATA_HANDLING if provider.name == "anthropic" else [],
    )
    session.add(run)
    records.audit(session, participant_id, "research.live_run_prepared", "research_live_run", run.id,
                  {"snapshot_version": snap.version, "provider": run.provider, "model": run.model,
                   "observations": len(local_refs), "payload_sha256": run.payload_sha256})
    session.flush()
    return run


# --- Approval and execution ----------------------------------------------------------

def approve(session: Session, run_id: uuid.UUID, approval: dict, env: dict | None = None) -> ResearchLiveRun:
    run = session.scalar(select(ResearchLiveRun).where(ResearchLiveRun.id == run_id).with_for_update())
    if run is None:
        raise DomainError(404, "Live run not found.")
    if run.status != "awaiting_approval":
        raise DomainError(409, f"This run is {run.status}; an approval applies to one awaiting run only.")
    if not approval.get("approve_this_payload_for_this_run_only"):
        raise DomainError(422, "Approval requires confirming this payload for this run only.")
    for k in ("payload_sha256", "provider", "model", "endpoint"):
        if approval.get(k) != getattr(run, k):
            raise DomainError(409, f"The approved {k} does not match this run; nothing was sent.")
    provider = providers.live_provider(env)
    current = (provider.name, provider.model, provider.endpoint) if provider else None
    if current != (run.provider, run.model, run.endpoint):
        raise DomainError(409, "The configured provider or model changed since this run was prepared; prepare a new run.")
    if provider.blockers():
        raise DomainError(409, "The provider is not ready; nothing was sent.", {"blockers": provider.blockers()})
    run.approval = {"approved": True, "scope": "this run only", "payload_sha256": run.payload_sha256,
                    "provider": run.provider, "model": run.model, "endpoint": run.endpoint,
                    "statement": "I approve sending exactly this request, once, to this provider and model."}
    run.approved_at = datetime.now(timezone.utc)
    run.status = "running"
    records.audit(session, run.participant_id, "research.live_run_approved", "research_live_run", run.id,
                  {"payload_sha256": run.payload_sha256, "provider": run.provider, "model": run.model})
    session.flush()
    return run


def withdraw(session: Session, run_id: uuid.UUID) -> ResearchLiveRun:
    run = session.get(ResearchLiveRun, run_id)
    if run is None:
        raise DomainError(404, "Live run not found.")
    if run.status != "awaiting_approval":
        raise DomainError(409, f"This run is {run.status} and cannot be withdrawn.")
    run.status = "withdrawn"
    run.completed_at = datetime.now(timezone.utc)
    records.audit(session, run.participant_id, "research.live_run_withdrawn", "research_live_run", run.id, {})
    session.flush()
    return run


def _statements(output: dict) -> list[tuple[str, dict]]:
    out = [(f"input_issues[{n}]", s) for n, s in enumerate(output.get("input_issues", []))]
    out += [(f"established[{n}]", s) for n, s in enumerate(output.get("established", []))]
    for n, e in enumerate(output.get("competing_explanations", [])):
        for part in ("supporting", "contrary", "evidence_gaps"):
            out += [(f"competing_explanations[{n}].{part}[{m}]", s) for m, s in enumerate(e.get(part, []))]
        if e.get("assessment"):
            out.append((f"competing_explanations[{n}].assessment", e["assessment"]))
    out += [(f"remaining_uncertainty[{n}]", s) for n, s in enumerate(output.get("remaining_uncertainty", []))]
    comp = output.get("comparison_with_rules", {})
    for part in ("differences_from_rules", "unchanged"):
        out += [(f"comparison_with_rules.{part}[{n}]", s) for n, s in enumerate(comp.get(part, []))]
    return out


def _known_refs(payload: dict) -> dict[str, set[str]]:
    ev = {e["id"] for e in payload["evidence"]} | {c["ref"] for e in payload["evidence"] for c in e["claims"]}
    ev |= {d["ref"] for d in payload["laboratory_documentation"]}
    rules = {c["ref"] for c in payload["rules_based_interpretation"]["claims"]}
    rules |= {h["ref"] for h in payload["rules_based_interpretation"]["hypotheses"]}
    return {"observation": {o["ref"] for o in payload["observations"]}, "evidence": ev, "rule": rules}


def citation_check(payload: dict, output: dict) -> dict:
    known = _known_refs(payload)
    statements = _statements(output)
    unknown, uncited, established_unsupported, rule_only = [], [], [], []
    for path, s in statements:
        cited = s.get("observation_refs", []) + s.get("evidence_refs", []) + s.get("rule_refs", [])
        if not cited:
            uncited.append(path)
        # A rule ref names the proposal under review; it cannot by itself support a conclusion.
        if s.get("rule_refs") and not (s.get("observation_refs") or s.get("evidence_refs")) and \
                re.search(r"^established|\.(supporting|contrary|assessment)", path):
            rule_only.append(path)
        for kind, key in (("observation", "observation_refs"), ("evidence", "evidence_refs"), ("rule", "rule_refs")):
            unknown += [{"path": path, "ref": r} for r in s.get(key, []) if r not in known[kind]]
        if path.startswith("established") and not (s.get("observation_refs") or s.get("evidence_refs")):
            established_unsupported.append(path)
    for n, d in enumerate(output.get("distinguishing_information", [])):
        unknown += [{"path": f"distinguishing_information[{n}]", "ref": r}
                    for r in d.get("evidence_refs", []) if r not in known["evidence"]]
    text = json.dumps(output, ensure_ascii=False)
    scope = sorted({name for name, pat in SCOPE_PATTERNS.items() if re.search(pat, text, re.I)})
    return {"statements": len(statements), "uncited": uncited, "unknown_refs": unknown,
            "established_without_observation_or_evidence": established_unsupported,
            "supported_only_by_rule_refs": rule_only, "scope_flags": scope,
            "inferences": sum(1 for _, s in statements if s.get("is_inference")),
            "input_issues": len(output.get("input_issues", [])),
            "structurally_valid": not unknown and not established_unsupported and not rule_only,
            "note": "Checks that every citation exists in the approved payload. Whether a cited source supports a statement "
                    "needs reading the quote beside it."}


def compare_with_rules(payload: dict, output: dict) -> dict:
    rules = payload["rules_based_interpretation"]
    rule_evidence = {r for c in rules["claims"] for r in c["evidence_refs"]}
    cited_rules, cited_evidence = set(), set()
    for _, s in _statements(output):
        cited_rules |= set(s.get("rule_refs", []))
        cited_evidence |= set(s.get("evidence_refs", []))
    for e in output.get("competing_explanations", []):
        cited_rules |= set(e.get("rule_refs", []))
    differences = output.get("comparison_with_rules", {}).get("differences_from_rules", [])
    all_rules = [c["ref"] for c in rules["claims"]] + [h["ref"] for h in rules["hypotheses"]]
    return {"rule_refs_engaged": sorted(cited_rules & set(all_rules)),
            "rule_refs_not_engaged": [r for r in all_rules if r not in cited_rules],
            "evidence_cited_beyond_rules": sorted(cited_evidence - rule_evidence),
            "rules_explanations": len(rules["hypotheses"]),
            "live_explanations": len(output.get("competing_explanations", [])),
            "differences_from_rules": len(differences)}


def _payload_of(run: ResearchLiveRun) -> dict:
    content = run.request_body["messages"][0]["content"]
    return json.loads(content.split("\n", 1)[1])


def execute(run_id: uuid.UUID, env: dict | None = None) -> None:
    """Send the approved request once. Runs in a worker thread with its own session."""
    db.get_engine()
    session = db._SessionLocal()
    try:
        run = session.get(ResearchLiveRun, run_id)
        if run is None or run.status != "running" or not run.approval:
            return
        provider = providers.live_provider(env)
        resp = provider.send(run.request_body, TIMEOUT_S)
        run.latency_ms = resp.latency_ms
        run.completed_at = datetime.now(timezone.utc)
        if resp.status == "succeeded" and resp.body is not None:
            body = resp.body
            run.response_id, run.response_model, run.stop_reason = body.get("id"), body.get("model"), body.get("stop_reason")
            run.usage = body.get("usage")
            prices = run.estimate.get("price_usd_per_mtok") or {}
            u = run.usage or {}
            run.cost_usd = Decimal(str(round(u.get("input_tokens", 0) * prices.get("input", 0) / 1e6
                                             + u.get("output_tokens", 0) * prices.get("output", 0) / 1e6, 6)))
            text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
            try:
                run.output = json.loads(text)
            except ValueError:
                run.output = None
            if run.output is None:
                run.status, run.error = "failed", f"response was not the expected JSON (stop_reason {run.stop_reason})"
            else:
                payload = _payload_of(run)
                if run.kind == "apob_ldlp":
                    run.citation_check = citation_check(payload, run.output)
                    run.comparison = compare_with_rules(payload, run.output)
                else:
                    from app.research import partner  # partner builds on this module
                    run.citation_check = partner.citation_check(run.kind, payload, run.output)
                run.status = "succeeded"
        else:
            run.status, run.error = "failed", resp.error
        records.audit(session, run.participant_id, "research.live_run_completed", "research_live_run", run.id,
                      {"kind": run.kind, "status": run.status, "error": run.error, "response_model": run.response_model,
                       "input_tokens": (run.usage or {}).get("input_tokens"),
                       "output_tokens": (run.usage or {}).get("output_tokens")})
        session.commit()
    except Exception as exc:  # never log content
        log_exception_without_message(exc)
        session.rollback()
        run = session.get(ResearchLiveRun, run_id)
        if run is not None and run.status == "running":
            run.status, run.error, run.completed_at = "failed", type(exc).__name__, datetime.now(timezone.utc)
            session.commit()
    finally:
        session.close()


def start(run_id: uuid.UUID) -> None:
    threading.Thread(target=execute, args=(run_id,), daemon=True).start()


def to_out(run: ResearchLiveRun, snapshot_version: int | None = None) -> dict:
    return {
        "id": str(run.id), "status": run.status, "created_at": run.created_at.isoformat() if run.created_at else None,
        "snapshot_id": str(run.snapshot_id), "snapshot_version": snapshot_version,
        "provider": run.provider, "model": run.model, "endpoint": run.endpoint,
        "request_body": run.request_body, "payload_sha256": run.payload_sha256, "local_refs": run.local_refs,
        "evidence_ids": run.evidence_ids, "estimate": run.estimate, "limits": run.limits,
        "data_handling": run.data_handling, "approval": run.approval,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "response_id": run.response_id, "response_model": run.response_model, "stop_reason": run.stop_reason,
        "usage": run.usage, "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
        "latency_ms": run.latency_ms, "output": run.output, "citation_check": run.citation_check,
        "comparison": run.comparison, "error": run.error, "kind": run.kind, "context": run.context,
    }


def snapshot_version(session: Session, run: ResearchLiveRun) -> int | None:
    snap = session.get(ResearchSnapshot, run.snapshot_id)
    return snap.version if snap else None
