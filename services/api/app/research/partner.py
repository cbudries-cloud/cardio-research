"""Research partner: the cardiovascular overview, research priorities, question retrieval, and the
payloads of conversation and investigation runs.

Everything here is deterministic except the live runs it prepares, which go through the existing
per-run approval in live_run.py (D-050): prepare -> participant reads the exact request -> approve
-> one call. Nothing here prescribes, orders tests, starts an experiment or produces a forecast.

Status vocabulary used throughout:
  confirmed         accepted, confirmed by the participant against the source (participant_review)
  software_checked  accepted by the automated source check only; visible, not used for established conclusions
  awaiting_review   extracted, not yet accepted (or accepted with an open review flag)
  blocked           extracted with a blocking issue; needs correction before acceptance
Self-reported context is its own category; it is never upgraded to an observation.
"""

import json
import math
import re
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import calc_inputs
from app.models import (Observation, Participant, ParticipantContext, ResearchConversation, ResearchInvestigation,
                        ResearchLiveRun, ResearchMessage, ResearchNote, SourceDocument)
from app.research import discrepancy, live_run, providers, retrieval, runtime
from app.services import records
from app.services.records import DomainError
from app.services.series import test_key

# --- Domains -------------------------------------------------------------------------

DOMAINS = [
    {"id": "lipids", "title": "Atherogenic lipoproteins",
     "question": "What does the record show about atherogenic lipoprotein levels over time?",
     "keys": ["apolipoprotein_b", "ldl_cholesterol", "non_hdl_cholesterol", "total_cholesterol", "hdl_cholesterol",
              "triglycerides", "vldl_cholesterol"], "particles": True, "context": [],
     "terms": r"lipid|cholesterol|ldl|hdl|apo|particle|triglycer|lipoprotein|statin|discrepan"},
    {"id": "lpa", "title": "Lipoprotein(a)", "question": "Is Lp(a), a largely inherited factor, known?",
     "keys": ["lipoprotein_a"], "context": [], "terms": r"lp\(a\)|lpa|lipoprotein\s*\(?a|inherit|genetic"},
    {"id": "blood_pressure", "title": "Blood pressure", "question": "What is known about blood pressure?",
     "keys": [], "context": ["blood_pressure"], "terms": r"blood.?pressure|\bbp\b|hypertens|systolic|diastolic"},
    {"id": "metabolic", "title": "Glucose and body measurements",
     "question": "What is known about glycemia, diabetes status and body size?",
     "keys": ["hemoglobin_a1c", "glucose", "insulin"], "context": ["diabetes", "body"],
     "terms": r"glucose|a1c|insulin|diabet|metabolic|weight|bmi|waist|glyc"},
    {"id": "kidney", "title": "Kidney function", "question": "What is known about kidney function?",
     "keys": ["creatinine", "egfr"], "context": [], "terms": r"kidney|renal|egfr|creatinine"},
    {"id": "inflammation", "title": "Inflammation", "question": "What is known about inflammatory markers?",
     "keys": ["hs_crp"], "context": [], "terms": r"crp|inflamm"},
    {"id": "family_history", "title": "Family history", "question": "Is there premature cardiovascular disease in the family?",
     "keys": [], "context": ["family_history"], "terms": r"family|parent|father|mother|sibling|inherit|genetic"},
    {"id": "exposures", "title": "Age, sex, smoking and medications",
     "question": "Which non-laboratory risk inputs are known?",
     "keys": [], "context": ["demographics", "smoking", "medications"],
     "terms": r"smok|medicat|statin|drug|supplement|age\b|sex\b|prevent"},
]
DOMAIN_BY_ID = {d["id"]: d for d in DOMAINS}
# Questions about the record as a whole retrieve every domain.
WHOLE_RECORD = re.compile(r"\brisk\b|\bhistory\b|\brecords?\b|overall|whole|everything|unknown|uncertain|focus|"
                          r"priorit|explanation|\bmatters?\b", re.I)

# Context items the overview asks for, by context domain. Free-text values; nothing is imputed.
CONTEXT_ITEMS = {
    "demographics": ["Age (years)", "Sex"],
    "blood_pressure": ["Blood pressure reading (systolic/diastolic, mmHg)", "Blood-pressure medication"],
    "family_history": ["Premature cardiovascular disease in a first-degree relative",
                       "Family history details (relative, condition, age at event)"],
    "smoking": ["Smoking or nicotine use"],
    "medications": ["Lipid-lowering medication", "Other medications or supplements"],
    "body": ["Height", "Weight", "Waist circumference"],
    "diabetes": ["Diabetes diagnosis"],
    "other": ["Other context"],
}
PREVENT_CONTEXT = {"Age (years)": "age", "Sex": "sex", "Blood pressure reading (systolic/diastolic, mmHg)": "systolic blood pressure",
                   "Blood-pressure medication": "blood-pressure medication", "Smoking or nicotine use": "current smoking",
                   "Diabetes diagnosis": "diabetes status", "Lipid-lowering medication": "statin use",
                   "Height": "BMI (height)", "Weight": "BMI (weight)"}
RANGE_NOTE = ("A laboratory flag compares a value with the laboratory's reference interval. It is not an assessment of "
              "cardiovascular risk.")


def _years(d: date | None, today: date) -> float | None:
    return round((today - d).days / 365.25, 1) if d else None


def _status(o: Observation, eligible: set[uuid.UUID]) -> str:
    if o.id in eligible:
        return "confirmed" if o.verification_method == "participant_review" else "software_checked"
    if o.verification_status == "unverified" and records.blocking_issues(o.extraction_issues):
        return "blocked"
    return "awaiting_review"


def _particle(name: str) -> bool:
    return name.strip().lower() in runtime.PARTICLE_NAMES


def _domain_of(o: Observation) -> str | None:
    key = o.normalized_test_name
    for d in DOMAINS:
        if key in d["keys"] or (d.get("particles") and key is None and _particle(o.original_test_name)):
            return d["id"]
    return None


def _obs_row(o: Observation, status: str, today: date) -> dict:
    return {"observation_id": str(o.id), "key": test_key(o), "label": runtime.LABEL.get(o.normalized_test_name or "",
                                                                                       o.original_test_name),
            "test_as_written": o.original_test_name, "value_as_written": o.original_value,
            "comparator": o.value_comparator, "value": float(o.normalized_value) if o.normalized_value is not None else None,
            "unit": o.normalized_unit or o.original_unit, "collection_date": o.collection_date.isoformat() if o.collection_date else None,
            "years_ago": _years(o.collection_date, today), "status": status, "reported_as": o.reported_as,
            "lab_flag": o.lab_flag_raw, "reference_range": o.reference_range_raw, "laboratory": o.laboratory,
            "method": o.method, "value_origin": o.value_origin, "collection_method": o.collection_method,
            "specimen_type": o.specimen_type, "fasting": o.collection_conditions, "result_type": o.result_type}


def record_rows(session: Session, participant_id: uuid.UUID, today: date | None = None) -> list[dict]:
    """Every cardiovascular-domain observation that is accepted or awaiting review, with its status."""
    today = today or date.today()
    eligible = {o.id for o in calc_inputs.calculation_input_observations(session, participant_id)}
    successors = set(session.scalars(select(Observation.supersedes_observation_id).where(
        Observation.participant_id == participant_id, Observation.supersedes_observation_id.is_not(None))).all())
    rows = []
    for o in session.scalars(select(Observation).where(
            Observation.participant_id == participant_id,
            Observation.verification_status.in_(("accepted", "unverified")))).all():
        if o.id in successors:
            continue
        dom = _domain_of(o)
        if dom is None:
            continue
        rows.append({**_obs_row(o, _status(o, eligible), today), "domain": dom})
    rows.sort(key=lambda r: (r["collection_date"] or "9999", r["label"], r["reported_as"] != "current"))
    return rows


def current_context(session: Session, participant_id: uuid.UUID, today: date | None = None) -> list[dict]:
    """Self-reported context rows that no later row supersedes."""
    today = today or date.today()
    rows = session.scalars(select(ParticipantContext).where(ParticipantContext.participant_id == participant_id)
                           .order_by(ParticipantContext.created_at)).all()
    superseded = {r.supersedes_id for r in rows if r.supersedes_id}
    return [{"context_id": str(r.id), "domain": r.domain, "item": r.item, "value": r.value_text,
             "as_of": r.as_of.isoformat() if r.as_of else None, "years_ago": _years(r.as_of, today), "note": r.note,
             "entered_at": r.created_at.isoformat(), "supersedes_id": str(r.supersedes_id) if r.supersedes_id else None}
            for r in rows if r.id not in superseded]


def _series(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["label"], r["unit"], r["collection_method"], r["value_origin"])].append(r)
    out = []
    for (label, unit, method, origin), pts in groups.items():
        pts.sort(key=lambda r: (r["collection_date"] or "9999", r["reported_as"] != "current"))
        usable = [p for p in pts if p["status"] in ("confirmed", "software_checked")]
        numeric = [p for p in usable if p["value"] is not None and not p["comparator"]]
        change = None
        dated = sorted({p["collection_date"] for p in numeric if p["collection_date"]})
        if len(dated) >= 2:
            first = next(p for p in numeric if p["collection_date"] == dated[0])
            last = next(p for p in numeric if p["collection_date"] == dated[-1])
            change = {"from_date": dated[0], "to_date": dated[-1], "from": first["value_as_written"],
                      "to": last["value_as_written"], "difference": round(last["value"] - first["value"], 3),
                      "unit": unit, "draws": len(dated),
                      "note": "Difference between the first and last comparable draws only. It includes analytical and "
                              "within-person variation and says nothing about the path between draws."}
        notes = runtime._comparability([{**p, "fasting": p["fasting"]} for p in usable]) if usable else []
        if any(p["status"] in ("awaiting_review", "blocked") for p in pts):
            notes.append("Some points await review; they are shown but not used for conclusions.")
        out.append({"label": label, "unit": unit, "collection_method": method, "value_origin": origin,
                    "points": pts, "change": change, "comparability": notes,
                    "latest_usable": usable[-1] if usable else None})
    out.sort(key=lambda s: s["label"])
    return out


def _prevent_missing(ctx: list[dict]) -> list[str]:
    have = {PREVENT_CONTEXT[c["item"]] for c in ctx if c["item"] in PREVENT_CONTEXT}
    needed = ["age", "sex", "systolic blood pressure", "blood-pressure medication", "current smoking", "diabetes status",
              "statin use", "BMI (height)", "BMI (weight)"]
    return [n for n in needed if n not in have]


def _apob_run_statements(session: Session, participant_id: uuid.UUID) -> dict | None:
    """Established statements of the latest succeeded ApoB / LDL-P run. A statement the citation check flagged stays
    visible with its flag and is never part of the accepted summary."""
    run = session.scalar(select(ResearchLiveRun).where(
        ResearchLiveRun.participant_id == participant_id, ResearchLiveRun.kind == "apob_ldlp",
        ResearchLiveRun.status == "succeeded").order_by(ResearchLiveRun.created_at.desc()).limit(1))
    if run is None or not run.output:
        return None
    check = run.citation_check or {}
    flagged = set(check.get("established_without_observation_or_evidence", [])) | set(check.get("supported_only_by_rule_refs", []))
    items = []
    for n, s in enumerate(run.output.get("established", [])):
        path = f"established[{n}]"
        items.append({"path": path, "statement": s["statement"], "is_inference": s.get("is_inference", False),
                      "observation_ids": [run.local_refs[r] for r in s.get("observation_refs", []) if r in run.local_refs],
                      "evidence_refs": s.get("evidence_refs", []),
                      "accepted": path not in flagged,
                      "flag": "No observation or evidence is cited; kept out of accepted conclusions until resolved."
                              if path in flagged else None})
    return {"run_id": str(run.id), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "statements": items}


def overview(session: Session, participant_id: uuid.UUID, today: date | None = None) -> dict:
    today = today or date.today()
    rows = record_rows(session, participant_id, today)
    ctx = current_context(session, participant_id, today)
    apob = _apob_run_statements(session, participant_id)
    latest_inv = investigation_summaries(session, participant_id)
    domains = []
    for d in DOMAINS:
        drows = [r for r in rows if r["domain"] == d["id"]]
        dctx = [c for c in ctx if c["domain"] in d["context"]]
        usable = [r for r in drows if r["status"] in ("confirmed", "software_checked")]
        dates = sorted({r["collection_date"] for r in usable if r["collection_date"] and r["reported_as"] == "current"})
        latest = date.fromisoformat(dates[-1]) if dates else None
        shows, cannot = [], []
        if usable:
            shows.append(f"{len(dates)} draw date(s) with usable results"
                         + (f", spanning {_years(date.fromisoformat(dates[0]), latest)} years" if len(dates) > 1 else "") + ".")
            shows.append(f"Most recent usable draw: {dates[-1]} (about {_years(latest, today)} years ago)." if latest else
                         "Only reprinted previous results are usable.")
            confirmed = sum(r["status"] == "confirmed" for r in usable)
            shows.append(f"{confirmed} of {len(usable)} usable results confirmed by you against the source; the rest are "
                         "software-checked and not used for established conclusions.")
            if latest and (today - latest).days > 365:
                cannot.append("Current values: the most recent draw is more than a year old.")
            if len(dates) < 3:
                cannot.append("A trend: fewer than three comparable draw dates.")
        for c in dctx:
            shows.append(f"Self-reported: {c['item']} = {c['value']}" + (f" (as of {c['as_of']})" if c["as_of"] else " (date not given)") + ".")
        missing_items = [i for cd in d["context"] for i in CONTEXT_ITEMS[cd] if i not in {c["item"] for c in dctx}]
        if d["keys"] and not drows:
            cannot.append("No laboratory measurement in the record. Unknown, not normal.")
        if d["context"] and not dctx:
            cannot.append("Nothing entered yet. Unknown, not normal.")
        if any(r["lab_flag"] for r in usable):
            cannot.append(RANGE_NOTE)
        interpretations = []
        if d["id"] == "lipids" and apob:
            interpretations.append({"source": "ApoB / LDL-P live review", "run_id": apob["run_id"], "statements": apob["statements"]})
        for inv in latest_inv:
            if d["id"] in PRIORITY_DOMAINS.get(inv["priority_id"], []) and inv.get("latest"):
                interpretations.append({"source": f"Investigation: {inv['question']}", "investigation_id": inv["id"],
                                        "summary": inv["latest"].get("summary"),
                                        "conclusion_status": inv["latest"].get("conclusion_status")})
        domains.append({
            "id": d["id"], "title": d["title"], "question": d["question"],
            "state": "measured" if usable else "awaiting_review" if drows else "self_reported" if dctx else "unknown",
            "series": _series(drows), "context": dctx, "missing_context_items": missing_items,
            "shows": shows, "cannot_establish": cannot, "interpretations": interpretations,
            "awaiting_review": sum(r["status"] in ("awaiting_review", "blocked") for r in drows),
        })
    usable = [r for r in rows if r["status"] in ("confirmed", "software_checked") and r["collection_date"]
              and r["reported_as"] == "current"]
    all_dates = sorted({r["collection_date"] for r in usable})
    unknown = [d["title"] for d in domains if d["state"] == "unknown"]
    headline_shows = []
    if all_dates:
        headline_shows.append(f"{len(all_dates)} laboratory draw date(s) with usable cardiovascular results, from "
                              f"{all_dates[0]} to {all_dates[-1]}; the most recent is about "
                              f"{_years(date.fromisoformat(all_dates[-1]), today)} years old.")
    measured = [d["title"] for d in domains if d["state"] == "measured"]
    if measured:
        headline_shows.append("Measured: " + ", ".join(measured) + ".")
    reported = [d["title"] for d in domains if d["context"]]
    if reported:
        headline_shows.append("Self-reported context entered for: " + ", ".join(reported) + ".")
    missing_prevent = _prevent_missing(ctx)
    headline_cannot = []
    if missing_prevent:
        headline_cannot.append("A population risk estimate (PREVENT): missing " + ", ".join(missing_prevent) + ".")
    if all_dates and (today - date.fromisoformat(all_dates[-1])).days > 365:
        headline_cannot.append("Current levels: no draw in the past year.")
    if unknown:
        headline_cannot.append("Anything about " + ", ".join(unknown) + ": not in the record (unknown, not normal).")
    headline_cannot.append(RANGE_NOTE)
    prios = priorities(session, participant_id, today, rows=rows, ctx=ctx)
    return {
        "as_of": today.isoformat(),
        "headline": {"shows": headline_shows, "cannot_establish": headline_cannot,
                     "deserves_investigation": [{"id": p["id"], "title": p["title"]} for p in prios]},
        "domains": domains,
        "counts": {s: sum(r["status"] == s for r in rows) for s in ("confirmed", "software_checked", "awaiting_review", "blocked")},
        "context_items": CONTEXT_ITEMS,
    }


# --- Priorities ----------------------------------------------------------------------

PRIORITY_DOMAINS = {
    "lipid-exposure": ["lipids", "lpa", "exposures"],  # age and lipid-lowering medication shape exposure
    "missing-major-context": ["blood_pressure", "family_history", "exposures", "metabolic"],
    "particle-discordance": ["lipids"],
}
# Fixed, non-identifying literature queries (no digits, no record content). Tests enforce this.
PRIORITY_QUERIES = {
    "lipid-exposure": {"cumulative_apob_exposure": "cumulative apolipoprotein B exposure atherosclerotic cardiovascular disease",
                       "apob_within_person_variation": "apolipoprotein B within-person biological variation"},
    "missing-major-context": {"prevent_equations": "PREVENT equations cardiovascular risk validation",
                              "family_history_premature_cvd": "family history premature coronary heart disease risk"},
    "particle-discordance": {"apob_ldlp_discordance": "apolipoprotein B LDL particle number discordance",
                             "ldlp_method_agreement": "LDL particle number ion mobility nuclear magnetic resonance comparison"},
}
PRIORITY_EVIDENCE = {
    "lipid-exposure": ["zhang-2021-cumulative-ldl", "sniderman-2024-apob-discordance", "glavinovic-2022-apob-physiology"],
    "missing-major-context": ["sundstrom-2023-physic"],
    "particle-discordance": ["epstein-2025-apob-vs-ldlp", "glavinovic-2022-apob-physiology", "caulfield-2008-ion-mobility",
                             "williams-2014-four-subfraction-methods"],
}


def priorities(session: Session, participant_id: uuid.UUID, today: date | None = None, *, rows=None, ctx=None) -> list[dict]:
    """Up to three research questions from the record and its gaps. Order is a stated judgement (which question most
    constrains the overall picture), not a score."""
    today = today or date.today()
    rows = rows if rows is not None else record_rows(session, participant_id, today)
    ctx = ctx if ctx is not None else current_context(session, participant_id, today)
    usable = [r for r in rows if r["status"] in ("confirmed", "software_checked")]
    lipid = [r for r in usable if r["domain"] == "lipids" and r["reported_as"] == "current"]
    lipid_dates = sorted({r["collection_date"] for r in lipid if r["collection_date"]})
    out = []
    if lipid:
        age = _years(date.fromisoformat(lipid_dates[-1]), today) if lipid_dates else None
        out.append({
            "id": "lipid-exposure", "title": "Atherogenic lipoprotein exposure over the available history",
            "question": "What do the available ApoB and LDL measurements establish about lipoprotein exposure over time, "
                        "and how much of the lifetime exposure is unmeasured?",
            "relevance": "ApoB-containing lipoproteins are a causal, cumulative exposure for atherosclerosis; this is the "
                         "best-measured cardiovascular domain in the record.",
            "uncertain": f"{len(lipid_dates)} draw date(s); the most recent is about {age} years old; years before and between "
                         "draws are unmeasured; within-person variation is not established.",
            "could_change": "Whether lipid exposure is the main question to study, and what a baseline for any future "
                            "prediction has to be.",
            "domains": PRIORITY_DOMAINS["lipid-exposure"]})
    missing = _prevent_missing(ctx)
    fam = [c for c in ctx if c["domain"] == "family_history"]
    if missing or not fam:
        gaps = missing + ([] if fam else ["family history"])
        out.append({
            "id": "missing-major-context", "title": "Missing major risk context",
            "question": "Which missing context (blood pressure, family history, smoking, diabetes, age, sex) would most "
                        "change the overall picture, and what can be supplied now?",
            "relevance": "Blood pressure, smoking, diabetes, age and family history can each outweigh a single biomarker; "
                         "without them no population reference estimate is computable.",
            "uncertain": "Unknown: " + ", ".join(gaps) + ". Unknown is not normal.",
            "could_change": "Whether a population reference estimate exists; whether blood pressure or family history "
                            "displaces lipids as the main question.",
            "domains": PRIORITY_DOMAINS["missing-major-context"]})
    inputs = runtime.build_inputs(session, participant_id)
    res = discrepancy.investigate_discrepancy(inputs["observations"], runtime.load_ledger(),
                                              discrepancy.load_lab_docs(runtime.EVIDENCE_ROOT), env={})
    if res is not None:
        out.append({
            "id": "particle-discordance", "title": "Particle number versus ApoB on the same draw",
            "question": "Does the particle-number result change the lipid picture that ApoB gives, or is the difference "
                        "explained by measurement?",
            "relevance": "It matters only if it changes which atherogenic measure the record relies on. Listed because "
                         "it is unresolved, not because an unusual result is important by itself.",
            "uncertain": "The ApoB assay is unidentified; cross-method calibration is not established; there is no repeat.",
            "could_change": "Which particle measure is treated as primary in the lipid question above.",
            "domains": PRIORITY_DOMAINS["particle-discordance"]})
    for p in out:
        p["evidence_ids"] = PRIORITY_EVIDENCE[p["id"]]
        p["literature_queries"] = list(PRIORITY_QUERIES[p["id"]].values())
    return out[:3]


# --- Retrieval -----------------------------------------------------------------------

def select_domains(question: str) -> list[str]:
    hits = [d["id"] for d in DOMAINS if re.search(d["terms"], question, re.I)]
    if not hits or WHOLE_RECORD.search(question):
        return [d["id"] for d in DOMAINS]
    return hits


def retrieve(session: Session, participant_id: uuid.UUID, domains: list[str], today: date | None = None) -> dict:
    """What a question or investigation uses: usable observations and current context in the selected domains.
    Rows awaiting review are counted, not sent."""
    today = today or date.today()
    rows = [r for r in record_rows(session, participant_id, today) if r["domain"] in domains]
    ctx_domains = {c for d in domains for c in DOMAIN_BY_ID[d]["context"]}
    ctx = [c for c in current_context(session, participant_id, today) if c["domain"] in ctx_domains]
    used = [r for r in rows if r["status"] in ("confirmed", "software_checked")]
    dates = sorted({r["collection_date"] for r in used if r["collection_date"]})
    return {"domains": domains, "observations": used, "context": ctx,
            "not_sent_awaiting_review": sum(r["status"] in ("awaiting_review", "blocked") for r in rows),
            "period": {"first": dates[0], "last": dates[-1], "draw_dates": len(dates)} if dates else None,
            "unknown_domains": [d for d in domains if not any(r["domain"] == d for r in used)
                                and not any(c["domain"] in DOMAIN_BY_ID[d]["context"] for c in ctx)]}


# --- Payload -------------------------------------------------------------------------

def _rel(d: str | None, today: date) -> str:
    if not d:
        return "date not given"
    return f"about {_years(date.fromisoformat(d), today)} years before this request"


def build_payload(session: Session, participant_id: uuid.UUID, retrieved: dict, *, purpose: dict,
                  today: date, literature: list[dict] | None = None) -> tuple[dict, dict]:
    """(payload, local refs). Observations O1.., context C1.., accepted notes N1.., prior findings P1..,
    literature pmid:<id>, ledger records by ID. No calendar date, record ID, accession, lab code, name or file name."""
    obs = retrieved["observations"]
    dates = sorted({r["collection_date"] for r in obs if r["collection_date"]})
    draw = {d: n for n, d in enumerate(dates, 1)}
    labs = {lab: f"laboratory {chr(65 + n)}" for n, lab in enumerate(sorted({r["laboratory"] for r in obs if r["laboratory"]}))}
    refs: dict[str, str] = {}
    o_out = []
    for n, r in enumerate(obs, 1):
        ref = f"O{n}"
        refs[ref] = r["observation_id"]
        o_out.append({k: v for k, v in {
            "ref": ref, "domain": r["domain"], "test_as_written": r["test_as_written"],
            "value_as_written": r["value_as_written"], "comparator": r["comparator"], "unit": r["unit"],
            "result_type": r["result_type"], "value_origin": r["value_origin"], "method_named_in_report": r["method"],
            "specimen_type": r["specimen_type"], "collection_method": r["collection_method"], "fasting_as_printed": r["fasting"],
            "laboratory": labs.get(r["laboratory"]), "reference_range_as_printed": r["reference_range"],
            "lab_flag_as_printed": r["lab_flag"],
            "timing": (f"draw {draw[r['collection_date']]}, {_rel(r['collection_date'], today)}" if r["collection_date"] else "undated"),
            "reported_as": "previous result reprinted in a later report" if r["reported_as"] != "current" else "current result of that draw",
            "status": ("confirmed by the participant against the source report" if r["status"] == "confirmed"
                       else "software-checked transcription, not yet confirmed by the participant")}.items() if v is not None})
    c_out = []
    for n, c in enumerate(retrieved["context"], 1):
        ref = f"C{n}"
        refs[ref] = c["context_id"]
        c_out.append({"ref": ref, "domain": c["domain"], "item": c["item"], "value": c["value"],
                      "timing": _rel(c["as_of"], today), "note": c["note"],
                      "status": "self-reported by the participant; not a laboratory observation"})
    notes = session.scalars(select(ResearchNote).where(ResearchNote.participant_id == participant_id,
                                                       ResearchNote.status == "accepted").order_by(ResearchNote.created_at)).all()
    n_out = []
    for n, note in enumerate(notes, 1):
        refs[f"N{n}"] = str(note.id)
        n_out.append({"ref": f"N{n}", "kind": note.kind, "text": note.text,
                      "status": "accepted by the participant as a working note; not evidence and not a fact"})
    prior = []
    apob = _apob_run_statements(session, participant_id)
    if apob:
        inv_ref = {v: k for k, v in refs.items() if k.startswith("O")}
        for s in apob["statements"]:
            ref = f"P{len(prior) + 1}"
            refs[ref] = f"{apob['run_id']}:{s['path']}"
            prior.append({"ref": ref, "source": "earlier ApoB / LDL-P review (model output, participant has not checked its citations)",
                          "statement": s["statement"], "observation_refs": [inv_ref[i] for i in s["observation_ids"] if i in inv_ref],
                          "evidence_refs": s["evidence_refs"],
                          "status": "accepted into summaries" if s["accepted"] else "FLAGGED: cites no observation or evidence; not accepted"})
    for inv in investigation_summaries(session, participant_id):
        if inv.get("latest") and inv["latest"].get("summary"):
            ref = f"P{len(prior) + 1}"
            refs[ref] = f"{inv['latest']['run_id']}:summary"
            prior.append({"ref": ref, "source": f"earlier investigation: {inv['question']}", "statement": inv["latest"]["summary"],
                          "status": "model summary of an approved investigation; a proposal, not evidence"})
    ledger = runtime.load_ledger()
    ev_ids = purpose.get("evidence_ids") or sorted({e for d in retrieved["domains"] for p, ds in PRIORITY_DOMAINS.items()
                                                   if d in ds for e in PRIORITY_EVIDENCE[p]})
    payload = {
        "purpose": purpose["text"],
        "record_scope": {
            "domains_included": retrieved["domains"],
            "domains_with_no_information": retrieved["unknown_domains"],
            "draw_dates_included": len(dates),
            "span": (f"draw 1 {_rel(dates[0], today)} to draw {len(dates)} {_rel(dates[-1], today)}" if dates else "no draws"),
            "rows_awaiting_review_not_sent": retrieved["not_sent_awaiting_review"],
            "note": "Only cardiovascular-domain observations are included. Unknown domains are unknown, not normal.",
        },
        "observations": o_out,
        "self_reported_context": c_out,
        "accepted_notes": n_out,
        "prior_findings": prior,
        "evidence": [live_run._ledger_extract(ledger[e]) for e in ev_ids if e in ledger],
        "literature_candidates": literature or [],
    }
    if purpose.get("conversation"):
        payload["prior_conversation"] = purpose["conversation"]
    if purpose.get("previous_version"):
        payload["previous_version_of_this_investigation"] = purpose["previous_version"]
    if purpose.get("priorities"):
        payload["research_priorities"] = purpose["priorities"]
    return payload, refs


# --- Output schemas ------------------------------------------------------------------

_STATEMENT = {
    "type": "object", "additionalProperties": False,
    "required": ["statement", "is_inference", "observation_refs", "context_refs", "evidence_refs", "prior_refs"],
    "properties": {"statement": {"type": "string"}, "is_inference": {"type": "boolean"},
                   "observation_refs": {"type": "array", "items": {"type": "string"}},
                   "context_refs": {"type": "array", "items": {"type": "string"}},
                   "evidence_refs": {"type": "array", "items": {"type": "string"}},
                   "prior_refs": {"type": "array", "items": {"type": "string"}}},
}
_REF = {"$ref": "#/$defs/statement"}
_LIST = {"type": "array", "items": _REF}
_NOTE = {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["kind", "text"],
                                     "properties": {"kind": {"type": "string", "enum": ["working_hypothesis", "open_question", "context_note"]},
                                                    "text": {"type": "string"}}}}
_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "$defs": {"statement": _STATEMENT},
    "required": ["answer", "established", "interpretations", "unknown", "would_change_understanding", "proposed_notes"],
    "properties": {"answer": _STR, "established": _LIST, "interpretations": _LIST, "unknown": _LIST,
                   "would_change_understanding": _LIST, "proposed_notes": _NOTE},
}
_ITEM_WHY = lambda key: {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                    "required": [key, "why"], "properties": {key: _STR, "why": _STR}}}
INVESTIGATION_SCHEMA = {
    "type": "object", "additionalProperties": False, "$defs": {"statement": _STATEMENT},
    "required": ["summary", "conclusion_status", "learned", "interpretation_changes", "contradictory_or_limiting_evidence",
                 "applicability", "unresolved", "distinguishing_information", "next_step", "protocol", "proposed_notes"],
    "properties": {
        "summary": _STR,
        "conclusion_status": {"type": "string", "enum": ["specific_finding_established", "nothing_unusual_established",
                                                         "insufficient_information"]},
        "learned": _LIST,
        "interpretation_changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["previous", "current", "why"],
            "properties": {"previous": _STR, "current": _STR, "why": _REF}}},
        "contradictory_or_limiting_evidence": _LIST,
        "applicability": _LIST,
        "unresolved": _LIST,
        "distinguishing_information": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["information", "explanations_distinguished", "evidence_refs"],
            "properties": {"information": _STR, "explanations_distinguished": _STRS, "evidence_refs": _STRS}}},
        "next_step": {"type": "object", "additionalProperties": False,
                      "required": ["missing_history", "collectable_observations", "clinical_review_questions"],
                      "properties": {"missing_history": _ITEM_WHY("item"), "collectable_observations": _ITEM_WHY("observation"),
                                     "clinical_review_questions": _ITEM_WHY("question")}},
        "protocol": {"type": "object", "additionalProperties": False,
                     "required": ["stage", "title", "question", "hypothesis", "outcome", "measurement_window", "required_inputs",
                                  "comparison_baseline", "analysis_approach", "counts_against_hypothesis", "prediction",
                                  "limitations", "evidence_needed_before_intervention_prediction"],
                     "properties": {"stage": {"type": "string", "enum": ["observation_period", "intervention_response"]},
                                    "title": _STR, "question": _STR, "hypothesis": _STR, "outcome": _STR,
                                    "measurement_window": _STR, "required_inputs": _STRS, "comparison_baseline": _STR,
                                    "analysis_approach": _STR, "counts_against_hypothesis": _STR, "prediction": _STR,
                                    "limitations": _STRS, "evidence_needed_before_intervention_prediction": _STRS}},
        "proposed_notes": _NOTE,
    },
}

_RULES = """How to treat the inputs:
- Observations marked "confirmed" may support established conclusions. Software-checked observations are visible \
context: you may use them, but any statement that rests on them is not established; say so and mark it as an inference.
- Self-reported context (C refs) is the participant's report, not a measurement.
- Accepted notes (N refs), prior findings (P refs), earlier conversation and earlier versions are proposals to evaluate, \
not evidence. A prior finding marked FLAGGED must not be restated as established.
- Evidence records (ledger IDs, <record-id>/<claim-id>) carry verbatim quotes. Literature candidates (pmid:<id>) are \
abstracts only, not verified; say so when you rely on them and consider whether they apply to this person.
- A laboratory reference range is not a risk assessment. An old measurement is not a current value. Unknown domains \
are unknown, not normal. Do not reconstruct unmeasured years.
- Do not force an unusual finding. "Nothing unusual is established" is an acceptable conclusion.
- Do not add numbers that are not in the payload, except clearly labelled arithmetic on payload values.

Citations: every statement lists the refs it rests on (observation_refs O.., context_refs C.., evidence_refs ledger IDs \
or pmid:<id>, prior_refs N../P..). Cite only refs present in the payload. A statement with no ref belongs in unknown \
(or unresolved) and must say it rests on no record. Set is_inference true for your own inferences.

Scope: you may discuss what information or measurements could distinguish explanations and how a prospective \
observation could be designed. Do not prescribe or adjust medication or supplements, do not order tests, do not \
diagnose, do not state a numerical personal risk, and do not tell the person to start an experiment: there is no \
participating physician; questions for a clinician go in clinical-review items. Plain technical English."""

ANSWER_SYSTEM = """You are a research partner for one person studying their own cardiovascular records. You receive a \
JSON payload: their question, the observations retrieved for it (O1, O2, ...; timing is relative, no calendar dates), \
self-reported context, accepted notes, prior findings, evidence records and earlier conversation. No tools are \
available: answer from the supplied material only.

""" + _RULES + """

Produce the JSON object the output schema describes:
- answer: a direct plain-language answer to the question in a few sentences, without new claims beyond the lists below.
- established: what the confirmed observations and evidence establish.
- interpretations: inferences and their limits.
- unknown: what the record cannot establish, including missing domains.
- would_change_understanding: information that would most change the picture, and why.
- proposed_notes: at most three short notes the participant might choose to keep (working hypotheses, open questions, \
context to supply). They are saved only if the participant accepts them."""

INVESTIGATION_SYSTEM = """You are a research partner for one person studying their own cardiovascular records. You \
receive a JSON payload for one research question they selected: the observations retrieved for it (O1, O2, ...; timing \
is relative), self-reported context, accepted notes, prior findings, verified evidence records, literature candidates \
found by a non-identifying public search (abstracts only), and possibly the previous version of this investigation. \
No tools are available.

""" + _RULES + """

Produce the JSON object the output schema describes:
- summary: what was learned, in a few plain sentences.
- conclusion_status: specific_finding_established, nothing_unusual_established or insufficient_information.
- learned: what this investigation established or clarified, cited.
- interpretation_changes: for each interpretation that changed relative to the previous version or the prior findings, \
the previous reading, the current reading and why (cited). Empty if nothing defensible changed; do not invent change.
- contradictory_or_limiting_evidence: evidence that cuts against the leading reading or limits it.
- applicability: whether the cited studies apply to this person's measurements, methods and situation.
- unresolved: what remains open.
- distinguishing_information: information that could distinguish the remaining explanations.
- next_step: missing_history (history the person can supply), collectable_observations (observations the person \
could collect themselves or through routine measurement, with timing), clinical_review_questions (testing or \
treatment questions that need a clinician). Each with why.
- protocol: one candidate prospective protocol grounded in this question and the available data. If only an \
observation period is justified, stage is observation_period. Give the outcome, future measurement window, required \
inputs, comparison baseline, analysis approach, and the result that would count against the hypothesis. prediction \
states what the hypothesis predicts for the outcome in words; give a number only if it follows from payload values by \
stated arithmetic, and never a personalized forecast from two laboratory values. A biomarker prediction is not proof \
of better health; say so in limitations where relevant. evidence_needed_before_intervention_prediction lists what \
would be needed before predicting a response to any intervention.
- proposed_notes: at most three notes the participant might keep."""

SCOPE_PATTERNS = {
    "treatment": r"\b(start|stop|increase|decrease|begin|take)\w* (a |the |your )?(statin|medication|treatment|therapy|dose|supplement)",
    "diagnosis": r"\byou have (familial|hypercholesterol|hypertension|diabetes)|\bdiagnos(is|e|ed) (of|with) ",
    "personal_risk": r"\byour (personal |own )?(10|30)-year risk (is|of)\b|\b\d+(\.\d+)? ?% (10|30)-year risk",
    "test_ordering": r"\bI (have )?order(ed)?\b|\border(ing)? (a|an|another|the) .*test for you",
}


def statements(output: dict, kind: str) -> list[tuple[str, dict]]:
    keys = (("established", "interpretations", "unknown", "would_change_understanding") if kind == "conversation" else
            ("learned", "contradictory_or_limiting_evidence", "applicability", "unresolved"))
    out = [(f"{k}[{n}]", s) for k in keys for n, s in enumerate(output.get(k, []))]
    for n, c in enumerate(output.get("interpretation_changes", [])):
        out.append((f"interpretation_changes[{n}].why", c["why"]))
    return out


def known_refs(payload: dict) -> dict[str, set[str]]:
    ev = {e["id"] for e in payload["evidence"]} | {c["ref"] for e in payload["evidence"] for c in e["claims"]}
    ev |= {f"pmid:{l['pmid']}" for l in payload["literature_candidates"]}
    return {"observation": {o["ref"] for o in payload["observations"]},
            "context": {c["ref"] for c in payload["self_reported_context"]}, "evidence": ev,
            "prior": {n["ref"] for n in payload["accepted_notes"]} | {p["ref"] for p in payload["prior_findings"]}}


def citation_check(kind: str, payload: dict, output: dict) -> dict:
    known = known_refs(payload)
    confirmed = {o["ref"] for o in payload["observations"] if o["status"].startswith("confirmed")}
    flagged_prior = {p["ref"] for p in payload["prior_findings"] if p["status"].startswith("FLAGGED")}
    sts = statements(output, kind)
    unknown, uncited, unsupported, unconfirmed, on_flagged = [], [], [], [], []
    for path, s in sts:
        cited = [r for k in ("observation_refs", "context_refs", "evidence_refs", "prior_refs") for r in s.get(k, [])]
        if not cited:
            uncited.append(path)
        for kname, key in (("observation", "observation_refs"), ("context", "context_refs"), ("evidence", "evidence_refs"),
                           ("prior", "prior_refs")):
            unknown += [{"path": path, "ref": r} for r in s.get(key, []) if r not in known[kname]]
        if path.startswith(("established", "learned")):
            if not (s.get("observation_refs") or s.get("evidence_refs") or s.get("context_refs")):
                unsupported.append(path)
            obs = s.get("observation_refs", [])
            if obs and not s.get("is_inference") and not set(obs) <= confirmed:
                unconfirmed.append(path)
            if set(s.get("prior_refs", [])) & flagged_prior:
                on_flagged.append(path)
    for n, d in enumerate(output.get("distinguishing_information", [])):
        unknown += [{"path": f"distinguishing_information[{n}]", "ref": r} for r in d.get("evidence_refs", [])
                    if r not in known["evidence"]]
    text = json.dumps(output, ensure_ascii=False)
    scope = sorted({name for name, pat in SCOPE_PATTERNS.items() if re.search(pat, text, re.I)})
    return {"statements": len(sts), "uncited": uncited, "unknown_refs": unknown,
            "established_without_record_or_evidence": unsupported,
            "established_on_unconfirmed_observations": unconfirmed,
            "established_on_flagged_prior": on_flagged,
            "inferences": sum(1 for _, s in sts if s.get("is_inference")), "scope_flags": scope,
            "structurally_valid": not (unknown or unsupported or unconfirmed or on_flagged),
            "note": "Checks that every citation exists in the approved request and that established statements rest on "
                    "confirmed records or evidence. Whether a source supports a statement needs reading it."}


# --- Preparation ---------------------------------------------------------------------

LIMITS = {"conversation": {"max_tokens": 12000, "typical": 4000, "effort": "medium"},
          "investigation": {"max_tokens": 24000, "typical": 9000, "effort": "high"}}


def _prepare(session: Session, participant_id: uuid.UUID, kind: str, payload: dict, refs: dict, context: dict,
             env: dict | None = None) -> ResearchLiveRun:
    provider = providers.live_provider(env)
    if provider is None or not provider.model:
        raise DomainError(409, "No live provider and model are configured.")
    snap = runtime.create_snapshot(session, participant_id)
    lim = LIMITS[kind]
    system, schema = (ANSWER_SYSTEM, ANSWER_SCHEMA) if kind == "conversation" else (INVESTIGATION_SYSTEM, INVESTIGATION_SCHEMA)
    user_content = "Research payload (JSON):\n" + json.dumps(payload, indent=1, ensure_ascii=False)
    body = provider.build_request(system=system, user_content=user_content, output_schema=schema,
                                  max_tokens=lim["max_tokens"], effort=lim["effort"])
    label = session.get(Participant, participant_id).label
    docs = {str(d.id): d.original_filename for d in session.scalars(
        select(SourceDocument).where(SourceDocument.participant_id == participant_id))}
    forbidden = live_run._forbidden_values(snap.inputs, label, docs)
    forbidden["record_id"] |= {r["observation_id"] for r in record_rows(session, participant_id)}
    forbidden["record_id"] |= {c["context_id"] for c in current_context(session, participant_id)}
    leaked = live_run.scrub_violations(json.dumps(body, ensure_ascii=False), forbidden)
    if leaked:
        raise DomainError(409, "The outgoing request contains identifying values; it was not prepared.", {"categories": leaked})
    prices = provider.prices() or {}
    est_in = math.ceil(len(json.dumps(body, ensure_ascii=False)) / live_run.CHARS_PER_TOKEN_LOWER_BOUND)
    cost = lambda out_tokens: round(est_in * prices.get("input", 0) / 1e6 + out_tokens * prices.get("output", 0) / 1e6, 4)
    run = ResearchLiveRun(
        id=uuid.uuid4(), participant_id=participant_id, snapshot_id=snap.id, status="awaiting_approval",
        provider=provider.name, model=provider.model, endpoint=provider.endpoint, request_body=body,
        payload_sha256=live_run._sha(body), local_refs=refs, evidence_ids=[e["id"] for e in payload["evidence"]],
        estimate={"input_tokens_upper_estimate": est_in, "max_output_tokens": lim["max_tokens"],
                  "typical_output_tokens": lim["typical"], "price_usd_per_mtok": prices,
                  "cost_usd_typical": cost(lim["typical"]), "cost_usd_max": cost(lim["max_tokens"]),
                  "basis": f"input tokens over-estimated at {live_run.CHARS_PER_TOKEN_LOWER_BOUND} characters per token of "
                           "the request body; output capped by max_tokens. Prices retrieved 2026-10-26."},
        limits={"calls": 1, "retries": 0, "max_tokens": lim["max_tokens"], "effort": lim["effort"],
                "timeout_seconds": live_run.TIMEOUT_S, "tools": "none", "streaming": False,
                "schedule": "none: runs once, only when you approve it"},
        data_handling=providers.ANTHROPIC_DATA_HANDLING if provider.name == "anthropic" else [],
        kind=kind, context=context)
    session.add(run)
    records.audit(session, participant_id, "research.live_run_prepared", "research_live_run", run.id,
                  {"kind": kind, "snapshot_version": snap.version, "provider": run.provider, "model": run.model,
                   "observations": len(payload["observations"]), "context": len(payload["self_reported_context"]),
                   "payload_sha256": run.payload_sha256})
    session.flush()
    return run


def _retrieval_record(retrieved: dict) -> dict:
    """What a question used, by ID (kept in the database with the message and run)."""
    return {"domains": retrieved["domains"], "observation_ids": [r["observation_id"] for r in retrieved["observations"]],
            "context_ids": [c["context_id"] for c in retrieved["context"]], "period": retrieved["period"],
            "not_sent_awaiting_review": retrieved["not_sent_awaiting_review"], "unknown_domains": retrieved["unknown_domains"]}


# --- Conversations -------------------------------------------------------------------

def ask(session: Session, participant_id: uuid.UUID, conversation_id: uuid.UUID | None, text: str,
        env: dict | None = None) -> tuple[ResearchConversation, ResearchMessage, ResearchLiveRun]:
    text = text.strip()
    if not text:
        raise DomainError(422, "Ask a question.")
    if conversation_id is None:
        conv = ResearchConversation(id=uuid.uuid4(), participant_id=participant_id, title=text[:120])
        session.add(conv)
        session.flush()
    else:
        conv = session.get(ResearchConversation, conversation_id)
        if conv is None or conv.participant_id != participant_id:
            raise DomainError(404, "Conversation not found.")
    today = date.today()
    retrieved = retrieve(session, participant_id, select_domains(text), today)
    msg = ResearchMessage(id=uuid.uuid4(), conversation_id=conv.id, participant_id=participant_id, text=text,
                          retrieval=_retrieval_record(retrieved))
    session.add(msg)
    session.flush()
    history = []
    for m, run in conversation_turns(session, conv.id)[-4:-1]:
        if run is not None and run.status == "succeeded" and run.output:
            history.append({"question": m.text, "answer_summary": run.output.get("answer"),
                            "status": "earlier answer; a proposal, not evidence"})
    prios = [{k: p[k] for k in ("title", "relevance", "uncertain", "could_change")} for p in priorities(session, participant_id, today)]
    payload, refs = build_payload(session, participant_id, retrieved, today=today, purpose={
        "text": f"Question from the participant: {text}", "conversation": history, "priorities": prios})
    run = _prepare(session, participant_id, "conversation", payload, refs,
                   {"conversation_id": str(conv.id), "message_id": str(msg.id), "retrieval": msg.retrieval}, env)
    return conv, msg, run


def conversation_turns(session: Session, conversation_id: uuid.UUID) -> list[tuple[ResearchMessage, ResearchLiveRun | None]]:
    msgs = session.scalars(select(ResearchMessage).where(ResearchMessage.conversation_id == conversation_id)
                           .order_by(ResearchMessage.created_at)).all()
    runs = session.scalars(select(ResearchLiveRun).where(ResearchLiveRun.kind == "conversation",
                                                         ResearchLiveRun.context["conversation_id"].astext == str(conversation_id))
                           .order_by(ResearchLiveRun.created_at)).all()
    latest: dict[str, ResearchLiveRun] = {}
    for r in runs:
        latest[r.context.get("message_id")] = r
    return [(m, latest.get(str(m.id))) for m in msgs]


# --- Investigations ------------------------------------------------------------------

def literature_search(priority_id: str, env: dict | None = None) -> dict:
    return retrieval.search_literature(PRIORITY_QUERIES[priority_id], env)


def _version_summary(run: ResearchLiveRun, n: int) -> dict:
    o = run.output or {}
    return {"version": n, "run_id": str(run.id), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "summary": o.get("summary"), "conclusion_status": o.get("conclusion_status")}


def investigation_runs(session: Session, inv_id: uuid.UUID) -> list[ResearchLiveRun]:
    return list(session.scalars(select(ResearchLiveRun).where(
        ResearchLiveRun.kind == "investigation", ResearchLiveRun.context["investigation_id"].astext == str(inv_id))
        .order_by(ResearchLiveRun.created_at)).all())


def succeeded_versions(session: Session, inv_id: uuid.UUID) -> list[ResearchLiveRun]:
    return [r for r in investigation_runs(session, inv_id) if r.status == "succeeded"]


def investigation_summaries(session: Session, participant_id: uuid.UUID) -> list[dict]:
    out = []
    for inv in session.scalars(select(ResearchInvestigation).where(ResearchInvestigation.participant_id == participant_id)
                               .order_by(ResearchInvestigation.created_at)).all():
        done = succeeded_versions(session, inv.id)
        out.append({"id": str(inv.id), "priority_id": inv.priority_id, "question": inv.question,
                    "versions": len(done), "latest": _version_summary(done[-1], len(done)) if done else None})
    return out


def new_information(session: Session, participant_id: uuid.UUID, run: ResearchLiveRun) -> dict:
    """Records in the investigation's domains that were not in this version's request."""
    r = run.context.get("retrieval") or {}
    now = retrieve(session, participant_id, r.get("domains", []))
    obs_before, ctx_before = set(r.get("observation_ids", [])), set(r.get("context_ids", []))
    obs_now = {o["observation_id"] for o in now["observations"]}
    ctx_now = {c["context_id"] for c in now["context"]}
    return {"observations_added": sorted(obs_now - obs_before), "observations_no_longer_usable": sorted(obs_before - obs_now),
            "context_added": sorted(ctx_now - ctx_before), "context_superseded": sorted(ctx_before - ctx_now),
            "any": bool((obs_now ^ obs_before) or (ctx_now ^ ctx_before))}


def start_investigation(session: Session, participant_id: uuid.UUID, priority_id: str, env: dict | None = None
                        ) -> tuple[ResearchInvestigation, ResearchLiveRun]:
    """Create (or continue) the investigation of a priority: run the non-identifying literature search, then prepare
    one live run for approval. A new version keeps every earlier one."""
    today = date.today()
    prios = {p["id"]: p for p in priorities(session, participant_id, today)}
    inv = session.scalar(select(ResearchInvestigation).where(ResearchInvestigation.participant_id == participant_id,
                                                             ResearchInvestigation.priority_id == priority_id))
    if inv is None:
        if priority_id not in prios:
            raise DomainError(404, "That research priority is not available for this record.")
        p = prios[priority_id]
        inv = ResearchInvestigation(id=uuid.uuid4(), participant_id=participant_id, priority_id=priority_id, question=p["question"])
        session.add(inv)
        session.flush()
    p = prios.get(priority_id) or {"title": inv.question, "relevance": "", "uncertain": "", "could_change": ""}
    search = literature_search(priority_id, env)
    done = succeeded_versions(session, inv.id)
    previous = None
    if done:
        o = done[-1].output or {}
        previous = {"version": len(done), "summary": o.get("summary"), "conclusion_status": o.get("conclusion_status"),
                    "learned": [s["statement"] for s in o.get("learned", [])],
                    "unresolved": [s["statement"] for s in o.get("unresolved", [])],
                    "status": "earlier model output; a proposal to re-evaluate against the current record, not evidence"}
    retrieved = retrieve(session, participant_id, PRIORITY_DOMAINS[priority_id], today)
    payload, refs = build_payload(session, participant_id, retrieved, today=today, literature=search["candidates"], purpose={
        "text": f"Research question selected by the participant: {inv.question} Why it was proposed: {p['relevance']} "
                f"What is uncertain: {p['uncertain']} What resolving it could change: {p['could_change']}",
        "evidence_ids": PRIORITY_EVIDENCE[priority_id], "previous_version": previous})
    run = _prepare(session, participant_id, "investigation", payload, refs, {
        "investigation_id": str(inv.id), "priority_id": priority_id, "version": len(done) + 1,
        "retrieval": _retrieval_record(retrieved),
        "search": {"queries": search["queries"], "status": search["status"],
                   "pmids": [c["pmid"] for c in search["candidates"]]}}, env)
    return inv, run


def run_view(run: ResearchLiveRun, session: Session) -> dict:
    out = live_run.to_out(run, live_run.snapshot_version(session, run))
    out["kind"], out["context"] = run.kind, run.context
    return out


def resolve_refs(session: Session, run: ResearchLiveRun) -> dict:
    """Local labels for a run's refs (shown on private pages only)."""
    obs_ids = [v for k, v in run.local_refs.items() if k.startswith("O")]
    ctx_ids = [v for k, v in run.local_refs.items() if k.startswith("C")]
    obs = {str(o.id): o for o in session.scalars(select(Observation).where(Observation.id.in_([uuid.UUID(i) for i in obs_ids])))} if obs_ids else {}
    ctx = {str(c.id): c for c in session.scalars(select(ParticipantContext).where(ParticipantContext.id.in_([uuid.UUID(i) for i in ctx_ids])))} if ctx_ids else {}
    out = {}
    for ref, target in run.local_refs.items():
        if ref.startswith("O") and target in obs:
            o = obs[target]
            out[ref] = {"kind": "observation", "id": target, "label": f"{o.original_test_name} {o.original_value or ''} "
                        f"{o.normalized_unit or o.original_unit or ''} ({o.collection_date.isoformat() if o.collection_date else 'undated'})"}
        elif ref.startswith("C") and target in ctx:
            c = ctx[target]
            out[ref] = {"kind": "context", "id": target, "label": f"{c.item}: {c.value_text}"}
        elif ref.startswith("N"):
            note = session.get(ResearchNote, uuid.UUID(target))
            out[ref] = {"kind": "note", "id": target, "label": note.text if note else target}
        elif ref.startswith("P"):
            out[ref] = {"kind": "prior", "id": target, "label": "earlier finding"}
    payload = live_run._payload_of(run)
    for l in payload.get("literature_candidates", []):
        out[f"pmid:{l['pmid']}"] = {"kind": "literature", "id": l["pmid"], "label": l["title"],
                                     "url": f"https://pubmed.ncbi.nlm.nih.gov/{l['pmid']}/", "abstract": l.get("abstract")}
    for e in payload.get("evidence", []):
        out[e["id"]] = {"kind": "evidence", "id": e["id"], "label": e["title"]}
        for c in e["claims"]:
            out[c["ref"]] = {"kind": "evidence", "id": e["id"], "label": f"{e['title']}: {c['statement']}", "quote": c.get("quote")}
    for p in payload.get("prior_findings", []):
        if p["ref"] in out:
            out[p["ref"]]["label"] = p["statement"]
            out[p["ref"]]["status"] = p["status"]
    return out


# --- Next investigation ----------------------------------------------------------------

# Shown before an investigation of the priority has completed. Information, not instructions.
STATIC_NEXT = {
    "lipid-exposure": {
        "missing_history": [{"item": "Lipid-lowering medication or supplement use, with dates", "why": "Changes between draws cannot be read without it."},
                            {"item": "Earlier lipid results from other laboratories or records", "why": "Extends the measured history; unmeasured years stay unknown."}],
        "collectable_observations": [{"observation": "A repeat ApoB and lipid panel at the same laboratory and method, fasting status noted",
                                      "why": "A comparable third point is needed before within-person change can be separated from variation."}],
        "clinical_review_questions": [{"question": "Whether lipid testing or treatment is indicated, given the full history and family history",
                                       "why": "Testing and treatment decisions need a clinician."}]},
    "missing-major-context": {
        "missing_history": [{"item": "Age, sex, smoking or nicotine use, diabetes diagnosis, medications", "why": "Required inputs for a population reference estimate."},
                            {"item": "Premature cardiovascular disease in parents or siblings, with ages", "why": "Family history changes how lipid and other results are weighed."}],
        "collectable_observations": [{"observation": "Home blood-pressure readings with a validated upper-arm cuff (for example two readings morning and evening for seven days)",
                                      "why": "Blood pressure is entirely unknown in the record; several days of readings are more informative than one."}],
        "clinical_review_questions": [{"question": "How to interpret blood-pressure readings and whether any testing is indicated", "why": "Needs a clinician."}]},
    "particle-discordance": {
        "missing_history": [{"item": "Any other particle-number or ApoB results, with the laboratory and method", "why": "A repeat shows whether the difference persists."}],
        "collectable_observations": [{"observation": "ApoB and particle number repeated on one draw, methods identified",
                                      "why": "Separates a persistent difference from single-draw variation."}],
        "clinical_review_questions": [{"question": "Which atherogenic measure a clinician would rely on for decisions", "why": "Needs a clinician."}]},
}


def next_view(session: Session, participant_id: uuid.UUID) -> dict:
    prios = priorities(session, participant_id)
    if not prios:
        return {"priority": None, "source": "none", "next_step": None, "protocol": None, "run_id": None}
    invs = {i["priority_id"]: i for i in investigation_summaries(session, participant_id)}
    # The highest-priority question; if a lower one has a completed investigation and the first does not, use it.
    chosen = next((p for p in prios if invs.get(p["id"], {}).get("latest")), prios[0])
    inv = invs.get(chosen["id"])
    if inv and inv.get("latest"):
        run = session.get(ResearchLiveRun, uuid.UUID(inv["latest"]["run_id"]))
        o = run.output or {}
        return {"priority": chosen, "source": "investigation", "investigation_id": inv["id"],
                "version": inv["latest"]["version"], "run_id": str(run.id), "summary": o.get("summary"),
                "next_step": o.get("next_step"), "protocol": o.get("protocol"),
                "citation_check": run.citation_check, "refs": resolve_refs(session, run),
                "new_information": new_information(session, participant_id, run)}
    return {"priority": chosen, "source": "static", "investigation_id": inv["id"] if inv else None,
            "next_step": STATIC_NEXT[chosen["id"]], "protocol": None, "run_id": None,
            "protocol_blocked": "No protocol yet: run the investigation of this question first, so the protocol rests on the "
                                "record and the evidence it reviews."}
