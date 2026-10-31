"""Research runtime v0.1: versioned snapshot + rule-based personal investigation.

Deterministic. No language model and no external provider is called. Inputs are only
observations returned by the calculation boundary (calc_inputs.py), copied into the snapshot
with their verification method, so every snapshot can be re-read exactly as it was produced.
Published evidence comes from the public evidence ledger (research/), cited by claim ID.

What the rules may do: report measured values, dates, comparability, and positions relative to
the laboratory's printed ranges or to intervals the ledger quotes verbatim. What they must not
do: reconstruct unmeasured years, apply cohort event rates as
personal risk, infer a genetic diagnosis, or produce a numerical forecast.
"""

import hashlib
import json
import re
import statistics
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import calc_inputs
from app.models import Observation, ResearchSnapshot, ReviewFlag, SourceDocument
from app.services import records
from app.research import discrepancy
from app.services.series import test_key

RUNTIME_VERSION = "0.2"
RULES_SHA256 = hashlib.sha256(b"".join(
    (Path(__file__).parent / f).read_bytes() for f in ("runtime.py", "discrepancy.py", "readers.py", "providers.py", "retrieval.py")
)).hexdigest()
EVIDENCE_ROOT = Path("/research")

LIPIDS = ("apolipoprotein_b", "ldl_cholesterol", "non_hdl_cholesterol", "total_cholesterol",
          "hdl_cholesterol", "triglycerides")
GLYCEMIC = ("hemoglobin_a1c", "glucose", "insulin")
LABEL = {
    "apolipoprotein_b": "ApoB", "ldl_cholesterol": "LDL-C", "non_hdl_cholesterol": "Non-HDL-C",
    "total_cholesterol": "Total cholesterol", "hdl_cholesterol": "HDL-C", "triglycerides": "Triglycerides",
    "lipoprotein_a": "Lp(a)", "hemoglobin_a1c": "HbA1c", "glucose": "Glucose", "insulin": "Insulin",
    "hs_crp": "hs-CRP", "creatinine": "Creatinine", "egfr": "eGFR",
}
CONFIRMATION = {"participant_review": "confirmed by you against the source",
                "automated_check": "transcription checked by software; not yet confirmed by you"}


# --- Inputs --------------------------------------------------------------------------


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def build_inputs(session: Session, participant_id: uuid.UUID) -> dict[str, Any]:
    obs = calc_inputs.calculation_input_observations(session, participant_id)
    docs = {d.id: d for d in session.scalars(select(SourceDocument).where(
        SourceDocument.id.in_({o.source_document_id for o in obs if o.source_document_id})))}
    rows = []
    for o in obs:
        d = docs.get(o.source_document_id)
        loc = o.source_location or {}
        rows.append({
            "observation_id": str(o.id), "key": test_key(o), "recognized": o.normalized_test_name is not None,
            "test_as_written": o.original_test_name, "value_as_written": o.original_value,
            "value": _num(o.normalized_value), "comparator": o.value_comparator, "result_type": o.result_type,
            "unit": o.normalized_unit or o.original_unit, "collection_date": o.collection_date.isoformat(),
            "reported_as": o.reported_as, "verification_method": o.verification_method,
            "lab_flag": o.lab_flag_raw, "reference_range": o.reference_range_raw,
            "reference_low": _num(o.reference_range_low), "reference_high": _num(o.reference_range_high),
            "laboratory": o.laboratory, "method": o.method, "value_origin": o.value_origin,
            "collection_method": o.collection_method, "specimen_type": o.specimen_type,
            "fasting": o.collection_conditions, "accession": o.accession_id,
            "source_text": " ".join(t for t in (loc.get("text"), (loc.get("name_continuation") or {}).get("text"),
                                                " ".join(loc.get("cells") or [])) if t),
            "source_comments": loc.get("comments") or [],
            "panel_text": ((o.inherited_metadata or {}).get("collection_date") or {}).get("text"),
            "source": {"document_id": str(o.source_document_id) if o.source_document_id else None,
                       "document": d.original_filename if d else None, "page": loc.get("page"),
                       "column": loc.get("column", "result")},
        })
    review_candidates = []
    for o in session.scalars(select(Observation).where(
            Observation.participant_id == participant_id, Observation.verification_status.in_(("accepted", "unverified")),
            Observation.normalized_test_name.is_(None))).all():
        review_candidates.append({
            "observation_id": str(o.id), "test_as_written": o.original_test_name, "value_as_written": o.original_value,
            "unit": o.original_unit, "collection_date": o.collection_date.isoformat() if o.collection_date else None,
            "reference_range": o.reference_range_raw, "lab_flag": o.lab_flag_raw, "reported_as": o.reported_as,
            "result_type": o.result_type, "comparator": o.value_comparator,
            "value": _num(o.normalized_value), "reference_low": _num(o.reference_range_low),
            "reference_high": _num(o.reference_range_high),
            "source_status": o.verification_method if o.verification_status == "accepted" else "unverified",
            "blocking_issues": records.blocking_issues(o.extraction_issues),
            "source": {"document_id": str(o.source_document_id) if o.source_document_id else None,
                       "page": (o.source_location or {}).get("page")},
        })
    open_flags = session.scalar(select(func.count()).select_from(ReviewFlag).where(
        ReviewFlag.participant_id == participant_id, ReviewFlag.status == "open")) or 0
    unverified = session.scalars(select(Observation).where(
        Observation.participant_id == participant_id, Observation.verification_status == "unverified")).all()
    return {
        "observations": rows,
        "review_candidates": review_candidates,
        "excluded": {
            "unverified": len(unverified),
            "unverified_blocked": sum(1 for o in unverified if records.blocking_issues(o.extraction_issues)),
            "open_flags": open_flags,
        },
    }


# --- Helpers -------------------------------------------------------------------------


def _series(inputs: dict) -> dict[tuple, list[dict]]:
    """Comparable series: same test, unit, collection method and calculated/direct origin."""
    out: dict[tuple, list[dict]] = defaultdict(list)
    for r in inputs["observations"]:
        out[(r["key"], r["unit"], r["collection_method"], r["value_origin"])].append(r)
    for pts in out.values():
        pts.sort(key=lambda r: (r["collection_date"], r["reported_as"] != "current"))
    return out


def _by_key(inputs: dict, key: str) -> list[dict]:
    return sorted((r for r in inputs["observations"] if r["key"] == key),
                  key=lambda r: (r["collection_date"], r["reported_as"] != "current"))


def _ref(r: dict) -> dict:
    return {k: r[k] for k in ("observation_id", "test_as_written", "value_as_written", "unit", "collection_date",
                              "reported_as", "verification_method", "lab_flag", "reference_range", "laboratory",
                              "method", "fasting", "source")}


def _fmt(r: dict) -> str:
    hist = " (previous result reprinted in a later report)" if r["reported_as"] != "current" else ""
    flag = f", lab flag {r['lab_flag']}" if r["lab_flag"] else ""
    rng = f", lab range {r['reference_range']}" if r["reference_range"] else ""
    return f"{r['value_as_written']} {r['unit'] or ''} on {r['collection_date']}{hist}{flag}{rng}".replace("  ", " ")


def _above(r: dict) -> bool:
    """Above the printed range. A bounded result ("<10") counts only when the bound itself proves it."""
    if r["lab_flag"] and r["lab_flag"].upper().startswith("H"):
        return True
    v, hi, cmp = r["value"], r["reference_high"], r.get("comparator")
    if v is None or hi is None:
        return False
    if cmp in ("<", "<="):
        return False  # "<x" is never provably above anything from the bound alone
    if cmp in (">", ">="):
        return v >= hi
    return v > hi


def _below(r: dict) -> bool:
    if r["lab_flag"] and r["lab_flag"].upper().startswith("L"):
        return True
    v, lo, cmp = r["value"], r["reference_low"], r.get("comparator")
    if v is None or lo is None:
        return False
    if cmp in (">", ">="):
        return False
    if cmp in ("<", "<="):
        return v <= lo
    return v < lo


def _comparability(points: list[dict]) -> list[str]:
    notes = []
    labs = {p["laboratory"] for p in points if p["laboratory"]}
    if len(labs) > 1:
        notes.append(f"Performing-laboratory codes differ across points ({', '.join(sorted(labs))}).")
    origins = {p["value_origin"] for p in points}
    if len(origins) > 1:
        notes.append("Calculated and directly measured values are mixed; they are kept as separate series.")
    fasting = {(p["fasting"] or "not stated") for p in points if p["reported_as"] == "current"}
    if len(fasting) > 1:
        notes.append(f"Fasting status differs or is not stated at some draws ({', '.join(sorted(fasting))}).")
    if any(p["reported_as"] != "current" for p in points):
        notes.append("Some points are previous results reprinted by a later report; their own reference "
                     "range and accession were not printed.")
    units = {p["unit"] for p in points}
    if len(units) > 1:
        notes.append(f"Units differ ({', '.join(str(u) for u in units)}); values are not converted.")
    return notes


def _dates(points: list[dict]) -> list[str]:
    return sorted({p["collection_date"] for p in points})


def _evidence(ledger: dict, record_id: str, claim_ids: list[str], why: str) -> dict:
    rec = ledger.get(record_id)
    if rec is None:
        return {"record": record_id, "available": False, "why": why}
    claims = {c["id"]: c for c in rec["claims"]}
    return {
        "record": record_id, "available": True, "citation": _citation(rec["citation"]),
        "claims": [{"id": cid, "statement": claims[cid]["statement"],
                    "value": claims[cid].get("value"), "lower": claims[cid].get("lower"),
                    "upper": claims[cid].get("upper"), "unit": claims[cid].get("unit"),
                    "quote": (claims[cid].get("source_location") or {}).get("quote")}
                   for cid in claim_ids if cid in claims],
        "applicability_limits": rec.get("applicability_constraints", []),
        "why": why,
    }


def _citation(c: dict | str) -> str:
    if isinstance(c, str):
        return c
    authors = c.get("authors", [])
    who = (authors[0] + " et al.") if len(authors) > 1 else (authors[0] if authors else "")
    parts = [who, c.get("title"), c.get("journal"), str(c.get("year", "")), c.get("doi") and f"doi:{c['doi']}"]
    return ". ".join(p for p in parts if p)


def load_ledger(root: Path = EVIDENCE_ROOT) -> dict[str, dict]:
    ledger = {}
    for p in sorted((root / "evidence").glob("*.json")) if (root / "evidence").exists() else []:
        rec = json.loads(p.read_text())
        ledger[rec["id"]] = rec
    return ledger


# --- Rules ---------------------------------------------------------------------------


def rule_atherogenic_history(inputs: dict, ledger: dict) -> dict | None:
    present = {k: _by_key(inputs, k) for k in LIPIDS}
    present = {k: v for k, v in present.items() if v}
    if not ({"apolipoprotein_b", "ldl_cholesterol"} & set(present)):
        return None
    points = [p for k in LIPIDS for p in present.get(k, [])]
    dates = _dates(points)
    above = {k: sum(_above(p) for p in v) for k, v in present.items()}
    lines = [f"{LABEL[k]}: " + "; ".join(_fmt(p) for p in v) for k, v in present.items()]
    persist = [LABEL[k] for k, v in present.items() if len({p["collection_date"] for p in v}) >= 2 and all(_above(p) for p in v)]
    establishes = [f"Measured on {len(dates)} date(s) between {dates[0]} and {dates[-1]}."] + lines
    if persist:
        establishes.append("Above the laboratory's printed range at every measured date: " + ", ".join(persist) + ".")
    elif any(above.values()):
        establishes.append("Above the laboratory's printed range on at least one date: "
                           + ", ".join(LABEL[k] for k, n in above.items() if n) + ".")
    else:
        establishes.append("No value is above the laboratory's printed range.")
    conventional = None
    if not any(above.values()):
        conventional = ("Conventional interpretation: every atherogenic lipid marker is within the laboratory's "
                        f"printed range at each of the {len(dates)} measured date(s). Nothing in these records "
                        "supports a more unusual explanation; the open questions are about measurement "
                        "comparability and how little time the records cover.")
    return {
        "interpretation": conventional,
        "id": "atherogenic-lipoprotein-history",
        "kind": "finding",
        "priority": 3 if persist else (2 if any(above.values()) else 1),
        "title": "Atherogenic lipoproteins across the measured dates",
        "observations": [_ref(p) for p in points],
        "establishes": establishes,
        "does_not_establish": [
            f"Exposure before {dates[0]} or between measured dates; unmeasured years are not reconstructed.",
            "A cause for any value or change.",
            "A personal event risk. Laboratory ranges are reference intervals, not risk thresholds.",
        ],
        "comparability": _comparability(points),
        "evidence": [
            _evidence(ledger, "zhang-2021-cumulative-ldl", ["hr-cumulative-m2", "hr-twa-m2", "imputations"],
                      "Long-term LDL-C exposure carried information beyond a single midlife value in pooled US "
                      "cohorts; it does not license estimating your cumulative exposure from these points."),
        ],
        "competing_explanations": [
            "Real, stable level (the values reflect a persistent state).",
            "Within-person biological variation between draws.",
            "Fasting or non-fasting differences (triglycerides and calculated LDL-C are sensitive to them).",
            "Calculation or assay differences between laboratories or methods.",
            "A real change between draws (diet, weight, illness, medication).",
        ],
        "distinguishing_information": [
            "Repeat measurements under the same conditions (same laboratory, fasting status and method).",
            "A directly measured LDL-C or repeated apoB alongside calculated LDL-C.",
            "A dated record of medication, diet, weight and illness around each draw.",
        ],
        "decision_it_could_change": (
            "Whether 'persistently above the laboratory range across the measured interval' is a source-backed "
            "statement to bring to a clinician, and which marker this record should track as primary. "
            "Treatment decisions are outside this application."),
    }


ANCHOR_TOLERANCE = 5  # mg/dL; intervals are quoted at exact LDL-C values and never interpolated
_SNIDERMAN_ANCHORS = {70: "apob-range-ldl70", 100: "apob-range-ldl100", 130: "apob-range-ldl130",
                      160: "apob-range-ldl160", 190: "apob-range-ldl190"}


def rule_apob_ldl_concordance(inputs: dict, ledger: dict) -> dict | None:
    apob = {p["collection_date"]: p for p in _by_key(inputs, "apolipoprotein_b") if p["reported_as"] == "current"}
    ldl = {p["collection_date"]: p for p in _by_key(inputs, "ldl_cholesterol") if p["reported_as"] == "current"}
    pairs = [(ldl[d], apob[d]) for d in sorted(set(apob) & set(ldl))
             if apob[d]["value"] is not None and ldl[d]["value"] is not None
             and apob[d]["unit"] == "mg/dL" and ldl[d]["unit"] == "mg/dL"]
    if not pairs:
        return None
    rec = ledger.get("sniderman-2024-apob-discordance")
    claims = {c["id"]: c for c in rec["claims"]} if rec else {}
    establishes, unresolved, used = [], [], []
    for l, a in pairs:
        anchor = next((x for x in _SNIDERMAN_ANCHORS if abs(l["value"] - x) <= ANCHOR_TOLERANCE), None)
        if anchor is None or _SNIDERMAN_ANCHORS[anchor] not in claims:
            unresolved.append(
                f"On {l['collection_date']}: LDL-C {l['value_as_written']} mg/dL, apoB {a['value_as_written']} mg/dL. "
                "The ledger quotes apoB intervals only at LDL-C 70, 100, 130, 160 and 190 mg/dL; this LDL-C is not "
                f"within {ANCHOR_TOLERANCE} mg/dL of one, and the intervals are not interpolated, so concordance "
                "cannot be judged from the ledger.")
            continue
        c = claims[_SNIDERMAN_ANCHORS[anchor]]
        used.append(c["id"])
        pos = "above" if a["value"] > c["upper"] else ("below" if a["value"] < c["lower"] else "within")
        margin = min(abs(a["value"] - c["upper"]), abs(a["value"] - c["lower"]))
        establishes.append(
            f"On {l['collection_date']}: LDL-C {l['value_as_written']} mg/dL with apoB {a['value_as_written']} mg/dL. "
            f"In UK Biobank, about 95% of people with LDL-C {anchor} mg/dL had apoB {c['lower']}-{c['upper']} mg/dL; "
            f"this apoB is {pos} that interval, {margin:.1f} mg/dL from its nearest bound. A margin of a few mg/dL "
            "is not interpretable without a verified estimate of assay and within-person variation.")
    discordant = any(" above that interval" in e or " below that interval" in e for e in establishes)
    return {
        "id": "apob-ldl-concordance",
        "kind": "finding" if establishes else "unresolved_question",
        "priority": 3 if discordant else 1,
        "title": "Does apoB tell the same story as LDL-C?",
        "observations": [_ref(p) for pair in pairs for p in pair],
        "establishes": establishes + unresolved,
        "does_not_establish": [
            "That a discordance seen in a cohort distribution carries the cohort's event-rate difference for you; "
            "the rates compare distribution tails in UK Biobank and are not personal risk.",
            "Which particle subtype or mechanism explains any discordance.",
        ],
        "comparability": _comparability([p for pair in pairs for p in pair]),
        "evidence": [_evidence(ledger, "sniderman-2024-apob-discordance",
                               sorted(set(used)) + ["r-apob-ldl", "hr-residual-apob-given-ldl", "hr-residual-ldl-given-apob"],
                               "ApoB and LDL-C correlate strongly but diverge at a given LDL-C; the part of apoB not "
                               "explained by LDL-C was associated with events in the cohort, the reverse was not.")],
        "competing_explanations": [
            "Concordant markers: apoB adds little beyond LDL-C at this point.",
            "More, smaller cholesterol-poorer particles (apoB high relative to LDL-C), often with higher triglycerides.",
            "Calculated LDL-C error (equation behaviour at the measured triglycerides, non-fasting sample).",
        ],
        "distinguishing_information": [
            "Repeat apoB with a directly measured LDL-C, fasting, at the same laboratory.",
            "Triglycerides at each paired draw.",
        ],
        "decision_it_could_change": "Whether apoB rather than LDL-C becomes the primary lipid marker tracked in this record.",
    }


PARTICLE_NAMES = ("ldl particle number", "ldl-p", "ldl p", "ldl small", "ldl medium", "hdl large",
                  "ldl peak size", "ldl pattern")


def _particle_rows(inputs: dict) -> list[dict]:
    return sorted((r for r in inputs["observations"]
                   if r["test_as_written"].strip().lower() in PARTICLE_NAMES),
                  key=lambda r: (r["collection_date"], r["test_as_written"]))


def rule_particle_measures_vs_apob(inputs: dict, ledger: dict) -> dict | None:
    """Particle-count measures (e.g. LDL particle number by ion mobility or NMR) against apoB
    from the same draw. Matched by name as written: these tests are outside the dictionary."""
    particles = _particle_rows(inputs)
    number = [p for p in particles if p["test_as_written"].strip().lower() in ("ldl particle number", "ldl-p", "ldl p")]
    if not number:
        return None
    apob = {p["collection_date"]: p for p in _by_key(inputs, "apolipoprotein_b") if p["reported_as"] == "current"}
    ldl = {p["collection_date"]: p for p in _by_key(inputs, "ldl_cholesterol") if p["reported_as"] == "current"}
    establishes, used = [], list(particles)
    opposite = False
    for n in number:
        a, l = apob.get(n["collection_date"]), ldl.get(n["collection_date"])
        line = f"On {n['collection_date']}: LDL particle number {_fmt(n)}"
        if a:
            used.append(a)
            line += f"; apoB {_fmt(a)}"
            if _above(n) != _above(a):
                opposite = True
        if l:
            used.append(l)
            line += f"; LDL-C {_fmt(l)}"
        establishes.append(line + ".")
        if a and a["laboratory"] != n["laboratory"]:
            establishes.append(f"ApoB and LDL particle number were reported by different performing-laboratory "
                               f"codes ({a['laboratory']}, {n['laboratory']}), i.e. different assays.")
    if opposite:
        establishes.append("The two particle-related measures fall on opposite sides of their own laboratory ranges "
                           "on the same draw: LDL particle number above its range, apoB within its range.")
    others = [p for p in particles if p not in number]
    if others:
        establishes.append("Subfractions on the same draw: " + "; ".join(f"{p['test_as_written']} {_fmt(p)}" for p in others) + ".")
    dates = {n["collection_date"] for n in number}
    if len(dates) == 1:
        establishes.append("LDL particle number was measured on one date only; it was not repeated at later draws.")
    return {
        "id": "particle-number-vs-apob",
        "kind": "unresolved_question",
        "priority": 4 if opposite else 2,
        "title": "LDL particle number and apoB disagree about the same draw",
        "observations": [_ref(p) for p in used],
        "establishes": establishes,
        "does_not_establish": [
            "Which measure is correct. No conversion between nmol/L particle counts and mg/dL apoB is applied.",
            "That the laboratory ranges for the two tests describe the same reference population or the same cut-point "
            "logic; they are printed by different laboratories.",
            "Any personal risk, diagnosis or cause.",
        ],
        "comparability": _comparability(used),
        "evidence": [
            {"record": None, "available": False,
             "why": "No evidence record on LDL particle number (ion mobility or NMR) versus apoB has been verified into "
                    "the ledger. A commonly stated premise, one apoB molecule per LDL particle, would lead one to expect "
                    "the two to agree; that premise is not yet a verified ledger record and is not relied on here."},
            _evidence(ledger, "sniderman-2024-apob-discordance", ["r-apob-ldl", "hr-residual-apob-given-ldl"],
                      "Covers apoB versus LDL-C only, not particle number by ion mobility or NMR; cited for what it "
                      "does and does not cover."),
        ],
        "competing_explanations": [
            "Assay disagreement: particle number and apoB are measured by different methods at different laboratories, "
            "and each laboratory's range reflects its own reference population or cut-points.",
            "A real excess of small, cholesterol-poor LDL particles that one assay captures and the other does not.",
            "Pre-analytical or analytical error in either measurement on that date.",
        ],
        "distinguishing_information": [
            "Both measures repeated on the same sample at a later draw.",
            "The laboratories' method documentation for each assay and the basis of each printed range.",
            "A verified evidence record comparing ion-mobility or NMR particle number with apoB.",
        ],
        "decision_it_could_change": (
            "Which particle measure this record treats as primary, and whether the elevated particle number is raised "
            "with a clinician as an isolated abnormal result or as a measurement conflict with apoB."),
    }


def _simple_marker_rule(key: str, title: str, evidence_gap: str, explanations: list[str],
                        distinguishing: list[str], decision: str):
    def rule(inputs: dict, ledger: dict) -> dict | None:
        pts = _by_key(inputs, key)
        if not pts:
            return None
        flagged = [p for p in pts if _above(p) or _below(p)]
        values = [p["value"] for p in pts if p["value"] is not None]
        spread = (max(values) / min(values)) if len(values) >= 2 and min(values) > 0 else None
        if not flagged and not (spread and spread >= 2):
            return None  # conventional: reported in the summary, not investigated
        establishes = [f"{LABEL.get(key, key)}: " + "; ".join(_fmt(p) for p in pts)]
        if flagged:
            establishes.append(f"Outside the laboratory's printed range on {len(flagged)} of {len(pts)} measurement(s).")
        if spread and spread >= 2:
            establishes.append(f"The highest value is {spread:.1f} times the lowest across the measured dates.")
        if len({p['collection_date'] for p in pts}) < 2:
            establishes.append("Measured on one date only.")
        return {
            "id": f"{key.replace('_', '-')}-values", "kind": "unresolved_question",
            "priority": 2 if flagged else 1, "title": title,
            "observations": [_ref(p) for p in pts], "establishes": establishes,
            "does_not_establish": ["A diagnosis, a cause, or a personal risk."],
            "comparability": _comparability(pts),
            "evidence": [{"record": None, "available": False, "why": evidence_gap}],
            "competing_explanations": explanations, "distinguishing_information": distinguishing,
            "decision_it_could_change": decision,
        }
    return rule


rule_lpa = _simple_marker_rule(
    "lipoprotein_a", "Lp(a) outside the laboratory range",
    "No Lp(a) evidence record has been verified into the ledger yet; none is cited.",
    ["A true level outside the range.", "An assay or unit issue (nmol/L and mg/dL are not interconvertible)."],
    ["The same assay and unit at any repeat measurement.", "A verified evidence record on Lp(a) stability and meaning."],
    "Whether Lp(a) is listed among the questions for clinical review. No genetic conclusion is drawn.")
rule_glycemic = _simple_marker_rule(
    "hemoglobin_a1c", "HbA1c outside the laboratory range or variable",
    "No glycemic evidence record has been verified into the ledger yet; none is cited.",
    ["A stable level outside the range.", "Assay or red-cell turnover effects on HbA1c.", "A real change between draws."],
    ["Fasting glucose and HbA1c at the same draws.", "Repeat under the same laboratory."],
    "Whether glycemia is listed among the questions for clinical review.")
rule_crp = _simple_marker_rule(
    "hs_crp", "hs-CRP outside the range or varying between draws",
    "No hs-CRP evidence record has been verified into the ledger yet; none is cited.",
    ["A persistent level.", "A transient rise from recent illness, injury or exercise.", "Assay variation."],
    ["Repeat measurement when well, with a note of recent illness or exertion."],
    "Whether hs-CRP can be treated as a stable characteristic in this record at all.")


def rule_reference_risk_inputs(inputs: dict, ledger: dict) -> dict:
    have = {k: _by_key(inputs, k)[-1] for k in ("total_cholesterol", "hdl_cholesterol", "egfr") if _by_key(inputs, k)}
    missing_profile = ["sex", "age (date of birth)", "systolic blood pressure", "diabetes status", "current smoking",
                       "blood-pressure medication", "statin use", "BMI (height and weight)"]
    return {
        "id": "reference-risk-not-computable", "kind": "unresolved_question", "priority": 2,
        "title": "The population reference estimate (PREVENT) cannot be computed yet",
        "observations": [_ref(p) for p in have.values()],
        "establishes": (["Laboratory inputs available: " + "; ".join(f"{LABEL[k]} {_fmt(p)}" for k, p in have.items())]
                        if have else ["No laboratory inputs for the reference equations are available."])
                       + ["Missing inputs that laboratory reports do not contain: " + ", ".join(missing_profile) + "."],
        "does_not_establish": ["Any risk estimate. Missing inputs are not imputed.",
                               "Eligibility: the equations apply at ages 30-79 (10-year) and 30-59 (30-year) only."],
        "comparability": [],
        "evidence": [{"record": None, "available": False,
                      "why": "PREVENT engine implemented and matched to the AHA calculator on 84 reference outputs "
                             "(docs/milestone-3-plan.md); profile inputs are not built yet."}],
        "competing_explanations": [],
        "distinguishing_information": ["Profile entries for the missing inputs, with dates."],
        "decision_it_could_change": "Whether a population reference estimate exists for this record, and for which horizons.",
    }


RULES = (rule_particle_measures_vs_apob, rule_atherogenic_history, rule_apob_ldl_concordance, rule_lpa,
         rule_glycemic, rule_crp)


def conventional_summary(inputs: dict, investigated: set[str]) -> list[dict]:
    out = []
    for (key, unit, method, origin), pts in sorted(_series(inputs).items(), key=lambda kv: tuple(str(x or "") for x in kv[0])):
        if key in investigated:
            continue
        out.append({"key": key, "label": LABEL.get(key, pts[0]["test_as_written"]), "unit": unit,
                    "collection_method": method, "value_origin": origin, "points": len(pts),
                    "dates": _dates(pts), "outside_lab_range": sum(_above(p) or _below(p) for p in pts),
                    "recognized": pts[0]["recognized"]})
    return out


def prediction_question(inputs: dict) -> dict | None:
    best = None
    for key in ("apolipoprotein_b", "ldl_cholesterol"):
        for (k, unit, method, origin), pts in _series(inputs).items():
            if k != key:
                continue
            dates = _dates(pts)
            if best is None or len(dates) > best[1]:
                best = (key, len(dates), unit, method, origin, pts, dates)
    if best is None:
        return None
    key, n, unit, method, origin, pts, dates = best
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(dates, dates[1:])]
    cadence = statistics.median(gaps) if gaps else None
    return {
        "question": f"What will the next {LABEL[key]} ({unit}; "
                    f"{'calculated' if origin == 'calculated' else 'measured' if origin == 'measured_direct' else 'method not stated'}; "
                    f"collection method {method}) be at the next routine draw?",
        "outcome": f"{LABEL[key]} value at the next draw from the same laboratory and method.",
        "window": (f"The next draw within 4-8 months after {dates[-1]} (observed spacing between draws: "
                   f"{', '.join(str(g) for g in gaps)} days)") if gaps else f"The next draw after {dates[-1]}.",
        "comparison_baselines": ["Persistence: the most recent value.", "Mean of all prior comparable values."],
        "scoring": "Absolute error of each baseline against the observed value, recorded before the draw.",
        "comparable_points_available": n,
        "no_forecast_because": [
            f"Only {n} comparable measurement date(s); a defensible interval needs at least 3 and preferably more.",
            "No verified estimate of within-person variation (analytical plus biological) is in the evidence ledger.",
            "No dated record of medication, diet, weight or illness changes between draws.",
            "The forecast store that saves predictions before outcomes (Milestone 4) is not built.",
        ],
        "not_initiated": "No experiment, treatment change or test order is proposed.",
    }


def investigate(inputs: dict, ledger: dict) -> dict[str, Any]:
    findings = [f for rule in RULES if (f := rule(inputs, ledger))]
    findings.append(rule_reference_risk_inputs(inputs, ledger))
    findings.sort(key=lambda f: -f["priority"])
    findings = findings[:5]
    investigated = {r["key"] for f in findings for r in inputs["observations"]
                    if r["observation_id"] in {o["observation_id"] for o in f["observations"]}}
    for f in findings:
        methods = [o["verification_method"] for o in f["observations"]]
        f["confirmation"] = {"observations": len(methods),
                             "confirmed_by_participant": methods.count("participant_review"),
                             "automated_check_only": methods.count("automated_check")}
        f["provisional"] = methods.count("automated_check") > 0
    verification_items = sorted(
        {o["observation_id"]: o for f in findings for o in f["observations"]
         if o["verification_method"] == "automated_check"}.values(),
        key=lambda o: (o["collection_date"], o["test_as_written"]))
    obs = inputs["observations"]
    unfamiliar_outside = [_ref(r) for r in sorted(obs, key=lambda r: (r["test_as_written"], r["collection_date"]))
                          if not r["recognized"] and (_above(r) or _below(r))]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in obs:
        if not r["recognized"] and r["value"] is not None:
            groups[(r["collection_date"], r["value"], r["unit"])].append(r)
    name_fragments = [[_ref(r) for r in g] for g in groups.values()
                      if len({r["test_as_written"].strip().upper() for r in g}) > 1]
    return {
        "findings": findings,
        "unfamiliar_outside_range": unfamiliar_outside,
        "possible_name_fragments": name_fragments,
        "conventional": conventional_summary(inputs, investigated),
        "prediction_question": prediction_question(inputs),
        "verification_items": verification_items,
        "history": {
            "dates": sorted({r["collection_date"] for r in obs}),
            "current_results": sum(r["reported_as"] == "current" for r in obs),
            "historical_results": sum(r["reported_as"] != "current" for r in obs),
            "excluded_from_snapshot": inputs["excluded"],
        },
        "capabilities": {
            "working": ["Import and parsing of the observed report layout", "Reconciliation per document",
                        "Versioned, append-only research snapshots", "Deterministic investigation rules",
                        "Citations to verified evidence-ledger claims", "PREVENT engine (not yet wired to profile inputs)"],
            "manual_or_pending": ["Participant confirmation of values against sources",
                                  "Profile inputs (age, sex, blood pressure, smoking, medication, BMI)",
                                  "Evidence records beyond the three verified papers",
                                  "Forecast store and scoring (Milestone 4)"],
            "not_used": ["Language-model reasoning in the runtime", "Any external provider"],
        },
    }


IRON_FAMILY = re.compile(r"\biron\b|saturation|ferritin|transferrin|tibc|binding capacity", re.I)


def clinician_review_queue(inputs: dict) -> list[dict]:
    """Abnormalities outside the cardiovascular research scope, for clinical review. Grouped where
    related measurements exist (iron studies). No interpretation, diagnosis or advice."""
    cands = [r for r in inputs.get("review_candidates", []) if r["reported_as"] == "current"]
    abnormal = [r for r in cands if _above(r) or _below(r)]
    queue, used = [], set()
    iron = [r for r in cands if IRON_FAMILY.search(r["test_as_written"])]
    if any(r in abnormal for r in iron):
        queue.append({
            "group": "Iron studies",
            "items": [{**r, "outside_lab_range": _above(r) or _below(r)} for r in sorted(iron, key=lambda r: (r["collection_date"] or "", r["test_as_written"]))],
            "note": "Reported abnormal iron-related results with their related measurements and source status. "
                    "For clinician review; this application does not interpret them, does not diagnose iron overload or "
                    "deficiency, and suggests no self-treatment.",
        })
        used |= {r["observation_id"] for r in iron}
    for r in sorted(abnormal, key=lambda r: (r["test_as_written"], r["collection_date"] or "")):
        if r["observation_id"] in used:
            continue
        queue.append({"group": r["test_as_written"], "items": [{**r, "outside_lab_range": True}],
                      "note": "Outside the laboratory range; outside this project's research scope. For clinician review."})
    return queue


def prediction_question_v02(inputs: dict, snapshot_date: date) -> dict | None:
    base = prediction_question(inputs)
    if base is None:
        return None
    last = max(r["collection_date"] for r in inputs["observations"])
    base["window"] = (f"The first draw collected after this snapshot was saved ({snapshot_date.isoformat()}). The latest "
                      f"imported draw is {last}; any draw collected between then and {snapshot_date.isoformat()} is not "
                      "prospective, because its result may already exist, and must not be used to score this question.")
    base["saved_before_outcome"] = True
    base["no_forecast_because"] = base["no_forecast_because"] + [
        "No personal response model is fitted: two measurements cannot support one."]
    base["corrected"] = ("v0.1 targeted 4-8 months after the last draw, a window that had already passed when the "
                         "snapshot was made.")
    return base


def _claims_index(research: dict | None) -> dict[str, str]:
    return {c["id"]: c["text"] for c in (research or {}).get("claims", [])}


def diff_claims(previous: dict | None, current: dict | None) -> dict:
    before, after = _claims_index(previous), _claims_index(current)
    return {"added": sorted(set(after) - set(before)), "withdrawn": sorted(set(before) - set(after)),
            "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
            "unchanged": sorted(k for k in set(before) & set(after) if before[k] == after[k])}


def build_outputs(inputs: dict, ledger: dict, lab_docs: dict, snapshot_date: date, previous: dict | None,
                  provider=None, env: dict | None = None) -> dict:
    verified = [r for r in inputs["observations"] if r["verification_method"] == "participant_review"]
    rules = investigate(inputs, ledger)  # v0.1 rules-based baseline, unchanged
    research_verified = discrepancy.investigate_discrepancy(verified, ledger, lab_docs, provider=provider, env=env)
    research_preview = discrepancy.investigate_discrepancy(inputs["observations"], ledger, lab_docs, provider=provider, env=env)
    concordance = next((f for f in rules["findings"] if f["id"] == "apob-ldl-concordance"), None)
    coverage = []
    if concordance and concordance["kind"] == "unresolved_question":
        coverage.append("The ApoB-vs-LDL-C cohort intervals in the ledger are quoted only at fixed LDL-C values; this record's "
                        "LDL-C is not near one, so concordance cannot be read from that paper. Evidence coverage, not a "
                        "biological finding.")
    coverage += (research_preview or {}).get("limitations", [])
    readiness = [
        "PREVENT cannot run: profile inputs (age, sex, systolic blood pressure, smoking, diabetes, medications, BMI) are "
        "not entered. Readiness issue, not a risk finding.",
        f"{len(inputs['observations']) - len(verified)} accepted observations are software-checked only; verified analysis "
        f"uses the {len(verified)} confirmed by the participant.",
    ]
    for step in (research_preview or {}).get("workflow", []):
        for b in step.get("blockers") or []:
            readiness.append(f"{step['step']}: {b}")
    biological = [f for f in rules["findings"] if f["id"] in ("atherogenic-lipoprotein-history", "particle-number-vs-apob")]
    prev_research = (previous or {}).get("research_v02", {}) if previous else {}
    return {
        "rules_baseline_v01": rules,
        "research_v02": {"verified": research_verified, "provisional_preview": research_preview},
        "biological_findings": [f["id"] for f in biological],
        "coverage_limitations": coverage,
        "readiness_issues": readiness,
        "clinician_review_queue": clinician_review_queue(inputs),
        "prediction_question": prediction_question_v02(inputs, snapshot_date),
        "diff_from_previous": {
            "verified": diff_claims(prev_research.get("verified"), research_verified),
            "provisional_preview": diff_claims(prev_research.get("provisional_preview"), research_preview),
        },
        "inputs_split": {"verified": len(verified), "provisional": len(inputs["observations"]) - len(verified)},
    }


def create_snapshot(session: Session, participant_id: uuid.UUID, ledger: dict | None = None,
                    provider=None, env: dict | None = None) -> ResearchSnapshot:
    ledger = load_ledger() if ledger is None else ledger
    lab_docs = discrepancy.load_lab_docs(EVIDENCE_ROOT)
    inputs = build_inputs(session, participant_id)
    previous = session.scalar(select(ResearchSnapshot).where(ResearchSnapshot.participant_id == participant_id)
                              .order_by(ResearchSnapshot.version.desc()).limit(1))
    outputs = build_outputs(inputs, ledger, lab_docs, date.today(), previous.outputs if previous else None,
                            provider=provider, env=env)
    outputs["evidence_ledger"] = {rid: rec.get("review", {}).get("status") for rid, rec in ledger.items()}
    version = (previous.version if previous else 0) + 1
    snap = ResearchSnapshot(id=uuid.uuid4(), participant_id=participant_id, version=version,
                            runtime_version=RUNTIME_VERSION, rules_sha256=RULES_SHA256,
                            inputs=inputs, outputs=outputs)
    session.add(snap)
    records.audit(session, participant_id, "research.snapshot_created", "research_snapshot", snap.id,
                  {"version": version, "observations": len(inputs["observations"]),
                   "verified": outputs["inputs_split"]["verified"],
                   "interpretation_execution": ((outputs["research_v02"]["provisional_preview"] or {})
                                                .get("interpretation") or {}).get("execution")})
    session.flush()
    return snap
