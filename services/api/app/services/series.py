"""Longitudinal display. Results are split into separate series whenever comparability
has not been established: different collection methods (capillary / venous / unknown),
different units, or calculated vs directly measured values. No series is ever merged by
conversion or correction factor."""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Observation, ReviewFlag

METHOD_LABEL = {"venous": "Venous", "capillary": "Capillary", "unknown": "Collection method unknown"}
ORIGIN_LABEL = {"calculated": "calculated", "measured_direct": "direct", "not_stated": None}


def test_key(obs: Observation) -> str:
    return obs.normalized_test_name or f"unrecognized:{obs.original_test_name.strip().lower()}"


def list_tests(session: Session, participant_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Observation.normalized_test_name, Observation.original_test_name,
               Observation.verification_status, func.count())
        .where(Observation.participant_id == participant_id,
               Observation.verification_status.in_(("accepted", "unverified")))
        .group_by(Observation.normalized_test_name, Observation.original_test_name,
                  Observation.verification_status)
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for norm, orig, status, n in rows:
        key = norm or f"unrecognized:{orig.strip().lower()}"
        entry = out.setdefault(key, {"key": key, "label": norm or orig, "recognized": norm is not None,
                                     "accepted": 0, "unverified": 0})
        entry[status] += n
    return sorted(out.values(), key=lambda e: (not e["recognized"], e["label"]))


def build_series(session: Session, participant_id: uuid.UUID, key: str, include_unverified: bool) -> dict[str, Any]:
    statuses = ("accepted", "unverified") if include_unverified else ("accepted",)
    stmt = select(Observation).where(
        Observation.participant_id == participant_id,
        Observation.verification_status.in_(statuses),
    )
    if key.startswith("unrecognized:"):
        stmt = stmt.where(Observation.normalized_test_name.is_(None),
                          func.lower(func.trim(Observation.original_test_name)) == key.split(":", 1)[1])
    else:
        stmt = stmt.where(Observation.normalized_test_name == key)
    observations = list(session.scalars(stmt).all())

    flagged = set()
    if observations:
        ids = [o.id for o in observations]
        for a, b in session.execute(
            select(ReviewFlag.observation_id, ReviewFlag.related_observation_id)
            .where(ReviewFlag.status == "open")
        ).all():
            flagged.update(x for x in (a, b) if x in ids)

    undated = [o for o in observations if o.collection_date is None]
    groups: dict[tuple, list[Observation]] = defaultdict(list)
    for o in observations:
        if o.collection_date is not None:
            groups[(o.collection_method, o.normalized_unit, o.value_origin)].append(o)

    series = []
    for (method, unit, origin), obs_list in sorted(groups.items(), key=lambda kv: (kv[0][0] != "venous", kv[0])):
        obs_list.sort(key=lambda o: (o.collection_date, o.created_at, o.id))
        ranges = sorted({o.reference_range_raw or "(none reported)" for o in obs_list})
        labs = sorted({o.laboratory or "(laboratory not stated)" for o in obs_list})
        notices = []
        if len(ranges) > 1:
            notices.append(
                "Reference ranges differ within this series (" + "; ".join(ranges) + "). Laboratory flags "
                "reflect each report's own range and are not directly comparable."
            )
        if len(labs) > 1:
            notices.append(f"Results come from {len(labs)} laboratory labels; inter-laboratory "
                           "differences have not been assessed.")
        label_parts = [METHOD_LABEL[method], unit or "no unit"]
        if ORIGIN_LABEL.get(origin):
            label_parts.append(ORIGIN_LABEL[origin])
        series.append({
            "collection_method": method,
            "unit": unit,
            "value_origin": origin,
            "label": " · ".join(label_parts),
            "notices": notices,
            "points": [
                {
                    "observation_id": str(o.id),
                    "collection_date": o.collection_date.isoformat(),
                    "value": float(o.value_numeric) if o.value_numeric is not None else None,
                    "comparator": o.value_comparator,
                    "verification_status": o.verification_status,
                    "has_open_flag": o.id in flagged,
                    "reference_range_raw": o.reference_range_raw,
                    "reference_range_low": float(o.reference_range_low) if o.reference_range_low is not None else None,
                    "reference_range_high": float(o.reference_range_high) if o.reference_range_high is not None else None,
                    "lab_flag_raw": o.lab_flag_raw,
                    "laboratory": o.laboratory,
                    "source_document_id": str(o.source_document_id) if o.source_document_id else None,
                }
                for o in obs_list
            ],
        })

    notices = []
    methods = {s["collection_method"] for s in series}
    if {"capillary", "venous"} <= methods:
        notices.append("Capillary and venous results are shown as separate series. Their comparability for "
                       "this test has not been established, so a difference between series is not a trend.")
    if "unknown" in methods and len(methods) > 1:
        notices.append("Some results have an unknown collection method and are kept in their own series.")
    units = {s["unit"] for s in series}
    if len(units) > 1:
        msg = "Results reported in different units are shown separately; no unit conversion is applied."
        if key == "lipoprotein_a":
            msg += (" Lp(a) mass (mg/dL) and molar (nmol/L) results cannot be reliably converted with a "
                    "universal factor.")
        notices.append(msg)
    if len({s["value_origin"] for s in series}) > 1:
        notices.append("Calculated and directly measured values are shown as separate series.")
    if undated:
        notices.append(f"{len(undated)} result(s) without a usable collection date are not plotted.")
    if include_unverified:
        notices.append("Unverified candidates are included and drawn as hollow points. They are not accepted "
                       "observations.")

    return {"key": key, "include_unverified": include_unverified, "series": series, "notices": notices}
