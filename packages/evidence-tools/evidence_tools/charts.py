"""Generate chart-input CSVs from chart specs and evidence claims.

    python -m evidence_tools.charts <research-dir>

The CSV is the stored chart input (values, intervals and source location per row). It is fully
determined by the spec's row mapping and the claims, so the validator can require an exact match.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from evidence_tools.schema import CHART_COLUMNS, ChartSpec, EvidenceRecord


def fmt(v: float | None, decimals: int) -> str:
    return "" if v is None else f"{v:.{decimals}f}"


def build_rows(spec: ChartSpec, evidence: EvidenceRecord) -> list[dict[str, str]]:
    claims = {c.id: c for c in evidence.claims}
    rows = []
    for r in spec.rows:
        c = claims.get(r.claim_id)
        if c is None:
            raise KeyError(f"chart {spec.id}: unknown claim {r.claim_id}")
        loc = c.source_location
        rows.append({
            "row_id": r.row_id,
            "claim_id": c.id,
            "group": r.group,
            "label": r.label,
            "series": r.series,
            "value": fmt(c.value, c.decimals),
            "lower": fmt(c.lower, c.decimals),
            "upper": fmt(c.upper, c.decimals),
            "decimals": str(c.decimals),
            "unit": c.unit,
            "provenance": c.provenance,
            "source_section": loc.section if loc else "derived",
            "source_element": loc.element if loc else c.derivation.explanation,  # type: ignore[union-attr]
        })
    return rows


def to_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CHART_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("research")
    evidence = {p.stem: EvidenceRecord.model_validate_json(p.read_text()) for p in (root / "evidence").glob("*.json")}
    for p in sorted((root / "charts").glob("*.json")):
        spec = ChartSpec.model_validate_json(p.read_text())
        (root / "charts" / spec.data_file).write_text(to_csv(build_rows(spec, evidence[spec.evidence_id])))
        print("wrote", spec.data_file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
