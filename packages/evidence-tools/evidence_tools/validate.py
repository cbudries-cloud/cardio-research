"""Validate the research directory: structure, cross-references, source fidelity, chart inputs.

    python -m evidence_tools.validate <research-dir> [--source-cache DIR]

Checks
- Every file parses against the schema (evidence_tools.schema).
- Every reported number (value, lower, upper) appears verbatim in its claim's source quote.
- With --source-cache, every quote appears verbatim in the cached full text <evidence-id>.txt
  (the cache is kept outside the repository; full texts are not redistributed).
- Derived claims recompute from their inputs.
- Every chart row matches its claim exactly (value, interval, unit, provenance, location).
- Research questions reference existing evidence and charts, and personal applicability stays
  "not_assessed" while no personal records have been imported.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from evidence_tools.charts import build_rows
from evidence_tools.schema import CHART_COLUMNS, BuildNote, ChartSpec, Claim, EvidenceRecord, ResearchQuestion

# No personal medical records have been imported into the research layer. Changing this is a
# recorded decision, made only together with an applicability assessment workflow.
PERSONAL_RECORDS_IMPORTED = False


@dataclass
class Corpus:
    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    questions: dict[str, ResearchQuestion] = field(default_factory=dict)
    charts: dict[str, ChartSpec] = field(default_factory=dict)
    chart_rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    build_notes: dict[str, BuildNote] = field(default_factory=dict)


def _norm(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace("\xa0", " ")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text)


def number_forms(x: float) -> set[str]:
    """Textual forms in which a reported number may appear (e.g. 0.85 -> '0.85', '.85')."""
    forms: set[str] = set()
    for d in range(0, 4):
        s = f"{abs(x):.{d}f}"
        if math.isclose(float(s), abs(x), abs_tol=1e-12):
            forms.add(s)
            if s.startswith("0."):
                forms.add(s[1:])
            if d == 0 and abs(x) >= 1000:
                forms.add(f"{int(abs(x)):,}".replace(",", " "))
                forms.add(f"{int(abs(x)):,}")
    return {("-" + f) if x < 0 else f for f in forms}


def number_in_text(x: float, text: str) -> bool:
    t = _norm(text)
    for form in number_forms(x):
        if re.search(r"(?<![\d.])" + re.escape(form) + r"(?![\d])", t):
            return True
        if x < 0 and re.search(r"(?<![\d.])-\s?" + re.escape(form[1:]) + r"(?![\d])", t):
            return True
    return False


def formatted_in_text(x: float, decimals: int, text: str) -> bool:
    """The number, written with the reported number of decimals, appears in the text."""
    s = f"{abs(x):.{decimals}f}"
    forms = {s, s[1:] if s.startswith("0.") else s}
    if decimals == 0 and abs(x) >= 1000:
        forms |= {f"{int(abs(x)):,}".replace(",", " "), f"{int(abs(x)):,}"}
    t = _norm(text)
    for f in forms:
        sign = r"-\s?" if x < 0 else ""
        if re.search(r"(?<![\d.])" + sign + re.escape(f) + r"(?![\d])", t):
            return True
    # Small whole numbers are often written as words ("One molecule of apo B 100 ...").
    word = _NUMBER_WORDS.get(abs(x)) if decimals == 0 and x == int(x) else None
    return bool(word and re.search(rf"\b{word}\b", t, re.I))


_NUMBER_WORDS = {float(i): w for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"])}


def load(root: Path) -> tuple[Corpus, list[str]]:
    corpus, errors = Corpus(), []

    def parse(model, path: Path):
        try:
            return model.model_validate_json(path.read_text())
        except Exception as e:  # noqa: BLE001 - report every schema failure
            errors.append(f"{path.relative_to(root)}: {e}")
            return None

    for p in sorted((root / "evidence").glob("*.json")):
        if (r := parse(EvidenceRecord, p)) is not None:
            corpus.evidence[r.id] = r
            if p.stem != r.id:
                errors.append(f"{p.name}: file name must equal id '{r.id}'")
    for p in sorted((root / "questions").glob("*.json")):
        if (q := parse(ResearchQuestion, p)) is not None:
            corpus.questions[q.id] = q
    for p in sorted((root / "charts").glob("*.json")):
        if (c := parse(ChartSpec, p)) is not None:
            corpus.charts[c.id] = c
            data = root / "charts" / c.data_file
            if not data.exists():
                errors.append(f"chart {c.id}: missing data file {c.data_file}")
                continue
            with data.open(newline="") as f:
                reader = csv.DictReader(f)
                if tuple(reader.fieldnames or ()) != CHART_COLUMNS:
                    errors.append(f"chart {c.id}: columns must be exactly {CHART_COLUMNS}")
                corpus.chart_rows[c.id] = list(reader)
    for p in sorted((root / "build-notes").glob("*.json")):
        if (b := parse(BuildNote, p)) is not None:
            corpus.build_notes[b.id] = b
    return corpus, errors


def _claim_value(claims: dict[str, Claim], ref: str) -> float:
    cid, _, part = ref.partition(".")
    c = claims[cid]
    return {"": c.value, "lower": c.lower, "upper": c.upper}[part]  # type: ignore[return-value]


def check(corpus: Corpus, source_cache: Path | None = None, only: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    for ev in corpus.evidence.values():
        claims = {c.id: c for c in ev.claims}
        cached = None
        if source_cache is not None and (only is None or ev.id in only):
            path = source_cache / f"{ev.id}.txt"
            if path.exists():
                cached = _norm(path.read_text())
            else:
                errors.append(f"{ev.id}: no cached full text at {path}")
        for c in ev.claims:
            if c.provenance == "reported":
                quote = c.source_location.quote  # type: ignore[union-attr]
                for name in ("value", "lower", "upper"):
                    v = getattr(c, name)
                    if v is not None and not formatted_in_text(v, c.decimals, quote):
                        errors.append(
                            f"{ev.id}/{c.id}: {name}={v:.{c.decimals}f} does not appear in the source quote"
                        )
                if cached is not None and _norm(quote) not in cached:
                    errors.append(f"{ev.id}/{c.id}: quote not found verbatim in cached full text")
            else:
                d = c.derivation
                assert d is not None and c.value is not None
                missing = [i for i in d.inputs if i.partition(".")[0] not in claims]
                if missing:
                    errors.append(f"{ev.id}/{c.id}: derivation inputs not found: {missing}")
                    continue
                vals = [_claim_value(claims, i) for i in d.inputs]
                if d.method == "divide_by_sqrt_2pi":
                    expected = vals[0] / math.sqrt(2 * math.pi)
                elif d.method == "difference":
                    expected = vals[0] - vals[1]
                else:  # range_width
                    expected = vals[1] - vals[0]
                if not math.isclose(round(expected, 2), c.value, abs_tol=0.0051):
                    errors.append(f"{ev.id}/{c.id}: derived value {c.value} != recomputed {expected:.4f}")
                if d.method == "divide_by_sqrt_2pi" and c.lower is not None:
                    src = claims[d.inputs[0].partition(".")[0]]
                    for name in ("lower", "upper"):
                        want = getattr(src, name) / math.sqrt(2 * math.pi)
                        if not math.isclose(round(want, 2), getattr(c, name), abs_tol=0.0051):
                            errors.append(f"{ev.id}/{c.id}: derived {name} != recomputed {want:.4f}")

    for chart in corpus.charts.values():
        ev = corpus.evidence.get(chart.evidence_id)
        if ev is None:
            errors.append(f"chart {chart.id}: unknown evidence {chart.evidence_id}")
            continue
        try:
            expected = build_rows(chart, ev)
        except KeyError as e:
            errors.append(str(e))
            continue
        rows = corpus.chart_rows.get(chart.id, [])
        if len(rows) != len(expected):
            errors.append(f"chart {chart.id}: {len(rows)} rows stored, {len(expected)} expected from spec")
        for got, want in zip(rows, expected):
            for k in CHART_COLUMNS:
                if got.get(k) != want[k]:
                    errors.append(f"chart {chart.id} row {want['row_id']}: {k} {got.get(k)!r} != claim {want[k]!r}")

    for q in corpus.questions.values():
        for eid in q.evidence_ids:
            if eid not in corpus.evidence:
                errors.append(f"question {q.id}: unknown evidence {eid}")
        for cid in q.chart_ids:
            if cid not in corpus.charts:
                errors.append(f"question {q.id}: unknown chart {cid}")
        if not PERSONAL_RECORDS_IMPORTED and q.personal_applicability.status != "not_assessed":
            errors.append(f"question {q.id}: personal applicability must be 'not_assessed' (no records imported)")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("research")
    cache = Path(argv[argv.index("--source-cache") + 1]) if "--source-cache" in argv else None
    # --only id1,id2: check cached quotes for these records only (others were checked when added).
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    corpus, errors = load(root)
    errors += check(corpus, cache, only)
    summary = {
        "evidence": len(corpus.evidence),
        "claims": sum(len(e.claims) for e in corpus.evidence.values()),
        "questions": len(corpus.questions),
        "charts": len(corpus.charts),
        "chart_rows": sum(len(r) for r in corpus.chart_rows.values()),
        "build_notes": len(corpus.build_notes),
        "source_cache_checked": cache is not None,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
