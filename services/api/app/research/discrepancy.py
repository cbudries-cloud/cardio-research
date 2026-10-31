"""Research workflow v0.2: ApoB versus LDL particle number.

verified snapshot -> question -> evidence retrieval -> applicability review -> competing
explanations -> source-linked interpretation.

Every claim lists the observation IDs and evidence claim IDs it depends on. A claim whose
supporting observation is absent is not produced (it is "withdrawn" relative to an earlier
snapshot); a claim whose evidence record is unavailable is replaced by an explicit limitation.
Values are read by ID from the snapshot and every comparison and conversion is ordinary code.
The narrative step in a snapshot is the labelled mock; a live model runs only through an approved
live run (app/research/live_run.py).

The ApoB / LDL-P arithmetic is a consistency check between two assays, with explicit units and
conversion assumptions. It never rejects an observation, decides which test is correct, or assigns
clinical risk.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.research import providers, readers, retrieval

QUESTION = ("When an ion-mobility LDL particle number and an ApoB measured on the same draw fall on "
            "opposite sides of their laboratory ranges, is the disagreement accurately extracted, "
            "reproducible and analytically interpretable, and does it change how cardiovascular risk "
            "should be interpreted?")
EVIDENCE_IDS = ["glavinovic-2022-apob-physiology", "epstein-2025-apob-vs-ldlp", "caulfield-2008-ion-mobility",
                "williams-2014-four-subfraction-methods"]
LAB_DOC = "quest-91604-ion-mobility"
TARGETS = [
    readers.ReadTarget("ldl_particle_number", names=("ldl particle number", "ldl-p", "ldl p")),
    readers.ReadTarget("apob", keys=("apolipoprotein_b",)),
    readers.ReadTarget("ldl_c", keys=("ldl_cholesterol",)),
    readers.ReadTarget("ldl_subfractions", names=("ldl small", "ldl medium", "hdl large", "ldl peak size", "ldl pattern")),
]
METHOD_TERMS = [
    ("ion_mobility", r"\bion mobility\b"), ("nmr", r"\bnmr\b|nuclear magnetic"),
    ("immunoturbidimetric", r"turbidimetr"), ("immunonephelometric", r"nephelometr"),
    ("calculated", r"\(calc\)|\bcalculated\b|martin|friedewald|sampson"), ("direct", r"\bdirect\b"),
]


def _claim(id: str, text: str, obs: list[str], evidence: list[str], kind: str) -> dict:
    return {"id": id, "text": text, "depends_on_observations": sorted(obs), "depends_on_evidence": evidence, "kind": kind}


def method_of(row: dict) -> dict:
    """Method stated in the source text for this row: its line, comments and panel heading.
    Never inferred from a laboratory code."""
    texts = [row.get("source_text") or "", row.get("method") or ""] + (row.get("source_comments") or []) + [row.get("panel_text") or ""]
    blob = " ".join(texts).lower()
    found = [name for name, pat in METHOD_TERMS if re.search(pat, blob)]
    return {"method": found[0] if found else "not_stated_in_report", "all_terms": found,
            "basis": "report text (result line, comments, panel heading)" if found else
                     "no method named in the report text; performing-laboratory code alone is not used"}


def _value(row: dict) -> float | None:
    """Exact numeric value or None. Bounded results (comparators) are never treated as exact."""
    if row.get("comparator") or row.get("result_type") not in ("quantity", "dimensionless"):
        return None
    return row.get("value")


def _ledger_claim(ledger: dict, rec: str, cid: str) -> dict | None:
    r = ledger.get(rec)
    return next((c for c in r["claims"] if c["id"] == cid), None) if r else None


CHECK_USE = ("Consistency check only. It does not reject either observation, does not show which test is correct, and "
             "does not assign clinical risk.")


def consistency_check(p: dict, a: dict, ledger: dict, lab_doc: dict | None) -> dict | None:
    """ApoB (mg/dL) converted to a total apoB-particle concentration (nmol/L) under each conversion
    assumption in the ledger, compared with LDL-P (nmol/L) from the same draw."""
    pv, av = _value(p), _value(a)
    if pv is None or av is None or a["unit"] != "mg/dL" or p["unit"] != "nmol/L":
        return None
    mass = _ledger_claim(ledger, "glavinovic-2022-apob-physiology", "apob100-mass")
    stoich = _ledger_claim(ledger, "glavinovic-2022-apob-physiology", "apob-per-ldl")
    factor = _ledger_claim(ledger, "epstein-2025-apob-vs-ldlp", "apob-particle-conversion-factor")
    assumptions = []
    if mass and stoich:
        assumptions.append({"label": f"apoB-100 mass {mass['value']:g} kDa",
                            "nmol_per_l_per_mg_per_dl": 1e4 / mass["value"],
                            "derivation": f"1 mg/dL = 10 mg/L; 10 mg/L / {mass['value']:g} kDa (g/mmol x 1000) = "
                                          f"{1e4 / mass['value']:.2f} nmol/L",
                            "evidence": ["glavinovic-2022-apob-physiology/apob100-mass",
                                         "glavinovic-2022-apob-physiology/apob-per-ldl"]})
    if factor:
        assumptions.append({"label": f"{factor['value']:g} mg/dL per nmol/L (authors' factor)",
                            "nmol_per_l_per_mg_per_dl": 1 / factor["value"],
                            "derivation": f"1 / {factor['value']:g} = {1 / factor['value']:.2f} nmol/L per mg/dL "
                                          f"(implies about {factor['value'] * 1e4:.0f} kDa per apoB-100)",
                            "evidence": ["epstein-2025-apob-vs-ldlp/apob-particle-conversion-factor"]})
    if not assumptions:
        return None
    rows = []
    for x in assumptions:
        total = av * x["nmol_per_l_per_mg_per_dl"]
        rows.append({**x, "apob_particles_nmol_per_l": round(total), "ldlp_to_apob_particle_ratio": round(pv / total, 2)})
    above = [r["ldlp_to_apob_particle_ratio"] > 1 for r in rows]
    outcome = ("ldlp_exceeds_apob_count_under_all_assumptions" if all(above) else
               "ldlp_within_apob_count_under_all_assumptions" if not any(above) else "depends_on_assumption")
    limitations = [
        "The ApoB assay is not named in the report and its calibration traceability is unknown.",
        "Ion-mobility LDL-P is a laboratory-developed test, not FDA cleared or approved"
        + (f" [lab-doc:{LAB_DOC}]" if lab_doc else "") + "; LDL-P assays are not standardized against each other or "
        "against ApoB [williams-2014-four-subfraction-methods; epstein-2025-apob-vs-ldlp, authors' limitation].",
        "The conversion depends on the assumed apoB-100 mass; the two sources imply different factors "
        + " and ".join(f"{r['nmol_per_l_per_mg_per_dl']:.2f}" for r in rows) + " nmol/L per mg/dL.",
        "Each value is a single measurement; analytical variation for total LDL-P is not stated in the method paper.",
        "ApoB counts VLDL, IDL and Lp(a) particles as well as LDL, so agreement would not show that LDL-P is accurate.",
    ]
    return {"inputs": {"ldl_particle_number": {"observation_id": p["observation_id"], "value": pv, "unit": "nmol/L",
                                               "method_stated": method_of(p)["method"]},
                       "apob": {"observation_id": a["observation_id"], "value": av, "unit": "mg/dL",
                                "method_stated": method_of(a)["method"]}},
            "expectation": "Each LDL particle carries one apoB-100 and ApoB also counts VLDL, IDL and Lp(a) particles, so "
                           "on a common, calibrated scale LDL-P (nmol/L) is expected to be at or below the ApoB-derived "
                           "particle count (nmol/L).",
            "assumptions": rows, "outcome": outcome, "use": CHECK_USE, "limitations": limitations}


def investigate_discrepancy(obs: list[dict], ledger: dict, lab_docs: dict, *, provider=None,
                            reader: readers.ClinicalRecordReader | None = None, env: dict | None = None) -> dict[str, Any] | None:
    reader = reader or readers.DeterministicRecordReader()
    by_id = {o["observation_id"]: o for o in obs}
    read = reader.read(obs, TARGETS)
    rows = {role: [by_id[i] for i in ids] for role, ids in read.found.items()}
    ldlp_rows = [r for r in rows["ldl_particle_number"] if r["reported_as"] == "current"]
    if not ldlp_rows:
        return None
    retr = retrieval.retrieve(ledger, EVIDENCE_IDS, ["apob_vs_ldlp_discordance", "ldlp_method_agreement"], env)
    limitations = [f"Evidence record '{m}' is unavailable; claims that depend on it are not made." for m in retr.missing_records]
    claims, hypotheses, checks = [], [], []
    draws = []
    for p in ldlp_rows:
        same = lambda role: next((r for r in rows[role] if r["collection_date"] == p["collection_date"]
                                  and r["reported_as"] == "current"), None)
        a, l = same("apob"), same("ldl_c")
        subs = [r for r in rows["ldl_subfractions"] if r["collection_date"] == p["collection_date"] and r["reported_as"] == "current"]
        draws.append((p, a, l, subs))

    # Q1: is each observation accurately extracted?
    q1 = []
    for p, a, l, subs in draws:
        for role, r in (("LDL particle number", p), ("ApoB", a), ("LDL-C", l)):
            if r is None:
                continue
            m = method_of(r)
            q1.append({"role": role, "observation_id": r["observation_id"], "collection_date": r["collection_date"],
                       "verification": r["verification_method"], "report": r["source"]["document"],
                       "page": r["source"]["page"], "accession": r.get("accession"), "laboratory_code": r["laboratory"],
                       "method": m["method"], "method_basis": m["basis"]})
            claims.append(_claim(f"extraction-{role.lower().replace(' ', '-')}-{r['collection_date']}",
                                 f"{role} on {r['collection_date']} was read from {r['source']['document']} page "
                                 f"{r['source']['page']}; verification: "
                                 f"{'confirmed by the participant' if r['verification_method'] == 'participant_review' else 'software-checked only'}; "
                                 f"method named in the report: {m['method'].replace('_', ' ')}.",
                                 [r["observation_id"]], [], "extraction"))
    doc = lab_docs.get(LAB_DOC)
    if doc and any(x["role"] == "LDL particle number" and x["method"] == "ion_mobility" for x in q1):
        claims.append(_claim("ldlp-method-documentation", "The report names ion mobility; Quest's public test directory "
                             f"describes test {doc['test_code']} ({doc['test']}) as ion mobility, laboratory-developed and "
                             "not cleared or approved by the FDA.",
                             [x["observation_id"] for x in q1 if x["role"] == "LDL particle number"], [f"lab-doc:{LAB_DOC}"],
                             "method"))
    if not any(x["role"] == "ApoB" and x["method"] not in ("not_stated_in_report",) for x in q1):
        limitations.append("The ApoB method is not named in the report text, and Quest's public directory did not yield "
                           "its ApoB methodology; the ApoB assay is unidentified.")

    # Q2: reproducible and analytically interpretable?
    stoich = _ledger_claim(ledger, "glavinovic-2022-apob-physiology", "apob-per-ldl")
    cv = _ledger_claim(ledger, "caulfield-2008-ion-mobility", "cv-subfraction-upper")
    n_dates = len({r["collection_date"] for r in rows["ldl_particle_number"]})
    q2 = [f"LDL particle number was measured on {n_dates} date(s); reproducibility cannot be assessed from a single "
          "measurement." if n_dates < 2 else f"LDL particle number was measured on {n_dates} dates."]
    claims.append(_claim("ldlp-measurement-count", q2[0], [r["observation_id"] for r in rows["ldl_particle_number"]],
                         [], "reproducibility"))
    for p, a, l, subs in draws:
        if cv and not any(c["id"] == "ldlp-analytical-variation" for c in claims):
            claims.append(_claim("ldlp-analytical-variation", f"The ion-mobility method paper reports intra- and interassay "
                                 f"variation below {cv['value']:g}% for LDL and HDL subfractions (not stated for total LDL "
                                 "particle number).", [p["observation_id"]], ["caulfield-2008-ion-mobility/cv-subfraction-upper"],
                                 "reproducibility"))
        pv, av = _value(p), _value(a) if a else None
        if a and pv is not None and av is not None and a["unit"] == "mg/dL" and p["unit"] == "nmol/L":
            check = consistency_check(p, a, ledger, doc)
            if check:
                checks.append(check)
                parts = "; ".join(f"assuming {r['label']} ({r['derivation']}), ApoB {a['value_as_written']} mg/dL corresponds "
                                  f"to about {r['apob_particles_nmol_per_l']} nmol/L of all apoB-containing particles, and "
                                  f"LDL-P {p['value_as_written']} nmol/L is {r['ldlp_to_apob_particle_ratio']:.2f} times that"
                                  for r in check["assumptions"])
                verdict = {"ldlp_exceeds_apob_count_under_all_assumptions":
                               "Under every listed assumption LDL-P is above the ApoB-derived count, so the two results are "
                               "not consistent with each other on a common scale; the check cannot say which, if either, "
                               "is inaccurate.",
                           "ldlp_within_apob_count_under_all_assumptions":
                               "Under every listed assumption LDL-P is at or below the ApoB-derived count, as expected.",
                           "depends_on_assumption": "Whether LDL-P exceeds the ApoB-derived count depends on the conversion "
                                                    "assumption."}[check["outcome"]]
                text = f"Consistency check (units: ApoB mg/dL, particle concentrations nmol/L): {parts}. {verdict} {CHECK_USE}"
                claims.append(_claim(f"apob-particle-count-{p['collection_date']}", text,
                                     [p["observation_id"], a["observation_id"]],
                                     sorted({e for r in check["assumptions"] for e in r["evidence"]}), "analytical"))
                q2.append(text)
            else:
                limitations.append("ApoB-to-particle consistency check not made: no ledger record supplies an apoB-100 mass "
                                   "or conversion factor.")
        elif a and (pv is None or av is None):
            limitations.append("One of the values is bounded or not a quantity; no conversion is made from a bound.")

    # Q3: does it change clinical risk interpretation?
    ep = ledger.get("epstein-2025-apob-vs-ldlp")
    q3 = []
    if ep and draws and draws[0][1] is not None:
        p, a = draws[0][0], draws[0][1]
        nmr = _ledger_claim(ledger, "epstein-2025-apob-vs-ldlp", "n-nmr-profiled-samples")
        text = ("In UK Biobank (full text reviewed), groups whose ApoB exceeded the level predicted from LDL particle number "
                "had higher event rates than the reference group; groups where LDL particle number exceeded the level "
                "predicted from ApoB showed no significant increase. The paper describes that reference group both as the "
                "whole population and as the concordant control group. "
                + ("LDL-P in that study was measured by Nightingale Health NMR, not ion mobility, and the authors state the "
                   "assays are not standardized and may disagree. " if nmr else "The study's LDL-P assay is unverified. ")
                + "Its ratios are unadjusted case-rate ratios. Discordance is defined by a zero-intercept line reported in "
                "Figure 1 (LDL-P = 0.001168 x ApoB, units not stated); its applicability to these units and these assays has "
                "not been established, so these records are not placed on the study's discordance scale. The laboratory "
                "flags on these records (each value against its own reference range) are a different comparison from the "
                "study's discordance and from the particle-count consistency check.")
        claims.append(_claim("risk-interpretation-epstein", text, [p["observation_id"], a["observation_id"]],
                             ["epstein-2025-apob-vs-ldlp/hr-apob-excess-30pct-cad",
                              "epstein-2025-apob-vs-ldlp/concordance-line-coefficient"]
                             + (["epstein-2025-apob-vs-ldlp/n-nmr-profiled-samples"] if nmr else []), "clinical_interpretation"))
        q3.append(text)
        q3.append("Neither this evidence nor these records establish a personal risk. Whether the result should change any "
                  "clinical interpretation is a question for a clinician; this application makes no recommendation.")
    elif not ep:
        limitations.append("No evidence record on ApoB versus LDL particle number outcomes is available; the clinical "
                           "interpretation question is unanswered.")

    # Competing explanations: hypothesis table.
    p, a, l, subs = draws[0]
    exceeds = bool(checks) and checks[0]["outcome"] == "ldlp_exceeds_apob_count_under_all_assumptions"
    corr = _ledger_claim(ledger, "epstein-2025-apob-vs-ldlp", "ldlp-platform-correlation-range")
    sub_flags = [s for s in subs if (s.get("lab_flag") or "").upper().startswith("H")]
    obs_ids = [p["observation_id"]] + ([a["observation_id"]] if a else [])
    confirmed = all(by_id[i]["verification_method"] == "participant_review" for i in obs_ids)
    hypotheses = [
        {"hypothesis": "Cross-assay scale difference: the ion-mobility particle count and the ApoB result (method not "
                       "identified) are not on a common, standardised scale.",
         "supporting": [x for x in [
             "Methods use different principles and agree only moderately; the authors call for standardisation "
             "[williams-2014-four-subfraction-methods]" if "williams-2014-four-subfraction-methods" in ledger else None,
             "The ion-mobility test is laboratory-developed and not FDA-cleared [lab-doc:quest-91604-ion-mobility]" if doc else None,
             f"LDL-P platforms (NMR, ion mobility, VAP) correlated only moderately (r {corr['lower']:.2f} to {corr['upper']:.2f}) "
             "in the outcome study authors' earlier comparison [epstein-2025-apob-vs-ldlp/ldlp-platform-correlation-range]"
             if corr else None,
             "LDL-P exceeds the ApoB-derived particle count under every listed conversion assumption [consistency check]"
             if exceeds else None,
             "Different performing-laboratory codes on the two rows" if a and a["laboratory"] != p["laboratory"] else None] if x],
         "contrary": [],
         "evidence_gaps": ["No supplied evidence compares ion-mobility LDL particle number with ApoB in absolute terms "
                           "(missing evidence, not evidence against)", "The ApoB method and its calibration are unidentified"],
         "assumptions": ["ApoB calibration traceable to the international reference",
                         "apoB-100 mass 512 to 550 kDa (the two ledger sources differ)"],
         "distinguishing": ["Both measured again on one sample, same laboratory (a reproducibility investigation, not proof "
                            "of accuracy)", "The laboratory's calibration documentation for each assay"],
         "depends_on_observations": obs_ids},
        {"hypothesis": "More small, cholesterol-poor LDL particles.",
         "supporting": [x for x in [
             "LDL particle number is high while LDL-C is within range" if l else None,
             f"{len(sub_flags)} LDL subfraction(s) flagged high on the same draw" if sub_flags else None] if x],
         "contrary": [x for x in [
             "Particle size changes cholesterol per particle, not apoB per particle: on a common scale, more small particles "
             "can raise LDL-P relative to LDL-C but would not put LDL-P above the ApoB particle count "
             "[glavinovic-2022-apob-physiology]; this holds only if both assays are on that common scale"
             if exceeds and stoich else None] if x],
         "evidence_gaps": [],
         "assumptions": ["One apoB-100 per LDL particle"],
         "distinguishing": ["ApoB and LDL particle number on the same sample: if the ApoB-derived count is at or above LDL-P, "
                            "this explanation remains possible"],
         "depends_on_observations": obs_ids + [s["observation_id"] for s in sub_flags]},
        {"hypothesis": "Analytical or pre-analytical variation in either single measurement (LDL particle number or ApoB); "
                       "neither result is asserted to be wrong.",
         "supporting": ["Each value was measured once"],
         "contrary": [],
         "evidence_gaps": ["Analytical variation for total LDL particle number is not stated in the method paper (the "
                           "reported figure is for subfractions and does not transfer)",
                           "The ApoB assay, and therefore its analytical variation, is unidentified"],
         "assumptions": [],
         "distinguishing": ["Repeat measurements of both (reproducibility only)"], "depends_on_observations": obs_ids},
        {"hypothesis": "Extraction error in this application.",
         "supporting": ["Values not yet confirmed by the participant"] if not confirmed else [],
         "contrary": ["Automated check found the value and unit verbatim in the source line"]
                     + (["The participant confirmed every value against the source report"] if confirmed else []),
         "evidence_gaps": [], "assumptions": [],
         "distinguishing": [] if confirmed else ["Participant confirmation against the source page"],
         "depends_on_observations": obs_ids},
    ]

    # Source-linked interpretation: labelled mock in snapshots; live only through an approved live run.
    summary = " ".join(c["text"] for c in claims if c["kind"] in ("analytical", "clinical_interpretation"))
    result = (provider or providers.MockProvider()).complete("interpretation", {"deterministic_summary": summary})
    return {
        "question": QUESTION,
        "workflow": [
            {"step": "verified snapshot", "executor": "deterministic"},
            {"step": "question", "executor": "fixed text"},
            {"step": "evidence retrieval", "executor": "ledger" + (" + PubMed (live)" if not retr.blockers else ""),
             "blockers": retr.blockers},
            {"step": "applicability review", "executor": "deterministic (ledger applicability constraints)"},
            {"step": "competing explanations", "executor": "deterministic hypothesis table"},
            {"step": "source-linked interpretation", "executor": f"provider:{result.provider} (live only via an approved "
             "live run)", "execution": result.execution,
             "blockers": result.blockers, "latency_ms": round(result.latency_ms, 3), "cost_usd": result.cost_usd},
        ],
        "reader": {"name": read.reader, "abstained": read.abstained, "errors": read.errors},
        "q1_extraction": q1,
        "q2_reproducibility_and_interpretability": q2,
        "consistency_checks": checks,
        "q3_clinical_interpretation": q3,
        "hypotheses": hypotheses,
        "claims": claims,
        "applicability": {rid: ledger[rid]["applicability_constraints"] for rid in retr.ledger_records},
        "evidence": [{"record": rid, "citation": ledger[rid]["citation"]["title"], "access":
                      "full text" if ledger[rid]["access"]["full_text_reviewed"] else "abstract only"} for rid in retr.ledger_records],
        "search": retr.search,
        "limitations": limitations,
        "interpretation": {"text": result.text, "execution": result.execution, "provider": result.provider,
                           "model": result.model, "error": result.error},
    }


def load_lab_docs(root: Path) -> dict:
    d = root / "lab-docs"
    return {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.exists() else {}
