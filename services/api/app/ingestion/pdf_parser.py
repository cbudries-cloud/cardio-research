"""Text-layer PDF laboratory-report parser.

Supported layouts, both located by the x-position of the header words, with each following
line's words assigned to columns by position:

1. A results table whose header row contains a test-name column (Test / Analyte / Component /
   Biomarker) and a result column (Result / Value), optionally Flag, Units and Reference Range.
2. A range-split table: "Test Name | In Range | Out of Range | Reference Range | Lab". The
   result sits in whichever range column it falls in; a trailing H/L in the out-of-range cell
   is the laboratory flag; the unit follows the range inside the reference-range cell. A
   "Previous Result (and Date)" column is never read as the current result; its contents
   become separate rows labelled reported_as="historical_in_later_report", dated by the date
   printed in that cell, with no accession and no reference range (neither is stated for it). Panel heading lines may
   carry their own "Collected:" date, which applies to the rows below them.

In both layouts, lines indented under the test-name column are comments, not results.
Report-level fields ("Collected:", "Reported:", "Specimen:", "Laboratory:", "Accession:", ...)
are read from "Label: value" text above the rows they apply to. Rows inherit them, and the
verbatim header text is kept in inherited_metadata so inherited values stay distinguishable
from values stated on the row itself (specimen_source "report_header" vs "row").

Not supported: image-only/scanned PDFs (no OCR), rotated tables, results that wrap
across lines. These produce an explicit status so the participant can enter values
manually.
"""

import io
import re
from dataclasses import dataclass, field

import pdfplumber

from app.ingestion.candidate import RawResult

PARSER_NAME = "pdf_text_columns"
PARSER_VERSION = "8"

# Multi-word headings, matched before single words. "prior" columns are recognised only so
# their contents are never mistaken for the current result.
HEADER_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("previous", "result", "and", "date"), "prior"),
    (("previous", "result"), "prior"),
    (("prior", "result"), "prior"),
    (("out", "of", "range"), "value_out"),
    (("out", "range"), "value_out"),
    (("in", "range"), "value_in"),
    (("reference", "range"), "reference_range"),
    (("reference", "interval"), "reference_range"),
    (("test", "name"), "test_name"),
    (("analyte", "name"), "test_name"),
)
HEADER_LABELS = {
    "test_name": ("test", "analyte", "component", "biomarker"),
    "value": ("result", "value"),
    "flag": ("flag",),
    "unit": ("units", "unit"),
    "reference_range": ("reference", "ref", "range"),
    "specimen": ("specimen",),
    "lab_code": ("lab",),
}
VALUE_KEYS = ("value", "value_in", "value_out")
FLAG_TOKENS = {"h", "l", "hh", "ll", "a", "aa", "high", "low", "abn", "abnormal", "crit"}
_UNIT_RE = re.compile(r"^(%|[a-zµμ0-9.^*]*/[a-zµμ0-9./^²]+|fl|pg|ratio|index|units?|copies)$", re.I)

META_LABELS = {
    "collection_date": ("collection date", "date collected", "collected", "specimen collected"),
    "report_date": ("report date", "date reported", "reported"),
    "specimen": ("specimen type", "specimen"),
    "collection_method": ("collection method",),
    "laboratory": ("laboratory", "performing lab", "lab"),
    "conditions": ("fasting", "collection conditions"),
    "result_status": ("report status", "result status"),
    "method": ("method",),
    "accession": ("accession", "accession no", "accession number", "specimen id", "requisition"),
    "received_date": ("received", "date received"),
}
_META_LOOKUP = {label: key for key, labels in META_LABELS.items() for label in labels}
_META_RE = re.compile(
    r"(?P<label>" + "|".join(sorted((re.escape(l) for l in _META_LOOKUP), key=len, reverse=True)) + r")\s*:",
    re.I,
)
# "Accession ABC123456" (label without a colon, a single identifier token containing a digit).
_ACCESSION_NO_COLON = re.compile(r"^(?:accession|specimen id|requisition)(?: (?:no\.?|number|#))?\s+([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*)$", re.I)
_HAS_NUMBER = re.compile(r"(?<![A-Za-z])\d")
_END_RE = re.compile(r"^(end of report|comments?\b|notes?\s*:|interpretation\b)", re.I)


@dataclass
class PdfParseResult:
    status: str
    message: str | None
    page_count: int
    results: list[RawResult] = field(default_factory=list)


def _group_lines(words: list[dict], tolerance: float = 3.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _detect_header(line: list[dict]) -> list[tuple[str, float]] | None:
    cols: list[tuple[str, float]] = []
    used: set[str] = set()
    tokens = [w["text"].strip().lower().rstrip(":") for w in line]
    i = 0
    while i < len(line):
        for phrase, key in HEADER_PHRASES:
            if tuple(tokens[i:i + len(phrase)]) == phrase:
                if key not in used:
                    cols.append((key, line[i]["x0"]))
                    used.add(key)
                i += len(phrase)
                break
        else:
            for key, labels in HEADER_LABELS.items():
                if key not in used and tokens[i] in labels:
                    cols.append((key, line[i]["x0"]))
                    used.add(key)
                    break
            i += 1
    keys = {k for k, _ in cols}
    if "test_name" in keys and keys & set(VALUE_KEYS) and len(cols) >= 3:
        return sorted(cols, key=lambda c: c[1])
    return None


def _split_reference_cell(cell: str | None) -> tuple[str | None, str | None, str | None]:
    """Split "65-99 mg/dL (calc)" into (range, unit, trailing qualifier), all verbatim."""
    if not cell:
        return None, None, None
    tokens = cell.split()
    for i, t in enumerate(tokens):
        if _UNIT_RE.match(t) and not re.fullmatch(r"[\d.]+/[\d.]+", t):
            rng = " ".join(tokens[:i]) or None
            rest = " ".join(tokens[i + 1:]) or None
            return rng, t, rest
    return cell, None, None


def _looks_like_reference(tokens: list[str]) -> bool:
    first = tokens[0]
    return bool(re.match(r"^[<>]=?\d|^\d+(\.\d+)?-\d", first) or first in ("<", ">")
                or any(_UNIT_RE.match(t) and not re.fullmatch(r"[\d.]+/[\d.]+", t) for t in tokens))


_DATE_TOKEN = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


def _prior_result(cell: str | None) -> tuple[str, str | None, str] | None:
    """'198 02/10/2024' or '5.5 H 02/10/2024' -> (value, flag, date). Anything else -> None."""
    if not cell:
        return None
    parts = cell.split()
    if len(parts) < 2 or not _DATE_TOKEN.match(parts[-1]):
        return None
    middle = parts[1:-1]
    if len(middle) > 1 or (middle and middle[0].lower() not in FLAG_TOKENS):
        return None
    return parts[0], (middle[0] if middle else None), parts[-1]


def _join_wrapped_names(rows: list[tuple[float, float, list[RawResult]]],
                        names: list[tuple[float, float, str, list[float]]]) -> None:
    """Join a name-only line to the adjacent result row when a long test name wrapped.

    The line must start where result names start (headings start further left) and sit within
    the table's normal line spacing. It joins the row above when that row is directly above,
    otherwise the row directly below (value printed on the last line). The original row text and
    the continuation text are both kept in source_location."""
    if not rows or not names:
        return
    tops = sorted(t for t, _, _ in rows)
    gaps = sorted(b - a for a, b in zip(tops, tops[1:]) if b - a > 1)
    spacing = gaps[len(gaps) // 2] if gaps else 12.0
    limit = min(spacing * 1.2, 14.0)
    for top, x0, text, bbox in names:
        above = [r for r in rows if 0 < top - r[0] <= limit and abs(r[1] - x0) <= 2]
        below = [r for r in rows if 0 < r[0] - top <= limit and abs(r[1] - x0) <= 2]
        if above:
            target, where = max(above, key=lambda r: r[0]), "after"
        elif below:
            target, where = min(below, key=lambda r: r[0]), "before"
        else:
            continue
        for res in target[2]:
            if res.source_location.get("name_continuation"):
                continue
            res.test_name = f"{res.test_name} {text}" if where == "after" else f"{text} {res.test_name}"
            res.source_location["name_continuation"] = {"text": text, "position": where, "bbox": bbox}


def _range_split_row(row: dict[str, str | None]) -> dict[str, str | None] | None:
    """Fold In Range / Out of Range / Reference Range cells into value, flag, unit, range."""
    in_cell, out_cell = row.get("value_in"), row.get("value_out")
    reference = row.get("reference_range")
    if in_cell and out_cell:
        out_parts = out_cell.split()
        if len(in_cell.split()) == 1 and not (len(out_parts) == 2 and out_parts[1].lower() in FLAG_TOKENS):
            # An in-range result whose reference text starts left of its heading, in the
            # out-of-range column ("98 | 65-99 mg/dL" or "30 | SEE NOTE").
            reference = " ".join(t for t in (out_cell, reference) if t)
            out_cell = None
        else:
            return None  # both columns hold a result: ambiguous, leave for manual entry
    cell = in_cell or out_cell
    if not cell:
        return None
    flag = None
    parts = cell.split()
    if out_cell and len(parts) > 1 and parts[-1].lower() in FLAG_TOKENS:
        flag, parts = parts[-1], parts[:-1]
    if len(parts) > 3:
        return None  # running text (a comment that starts at the margin), not a result
    if not reference and len(parts) > 1 and _looks_like_reference(parts[1:]):
        # Some tables print the reference range left of its heading, inside the result column.
        reference, parts = " ".join(parts[1:]), parts[:1]
    cell = " ".join(parts)
    rng, unit, qualifier = _split_reference_cell(reference)
    return {"value": cell, "flag": flag, "unit": row.get("unit") or unit, "reference_range": rng,
            "method": qualifier}


def _meta_from_line(text: str, anchored: bool = True) -> dict[str, str]:
    found: dict[str, str] = {}
    matches = list(_META_RE.finditer(text))
    if not matches or (anchored and matches[0].start() != 0):
        return found
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end():end].strip()
        key = _META_LOOKUP[m["label"].lower()]
        if value:
            found[key] = value
    return found


def parse_pdf(data: bytes, skipped: list[dict] | None = None) -> PdfParseResult:
    """Parse a text PDF. If `skipped` is given, every line inside a results table that contains
    a number but produced no result is appended to it with the reason (for reconciliation)."""

    def skip(reason: str, page_number: int, text: str) -> None:
        if skipped is not None and _HAS_NUMBER.search(text):
            skipped.append({"page": page_number, "reason": reason, "text": text})

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception:
        return PdfParseResult("failed", "The PDF could not be opened.", 0)

    with pdf:
        page_count = len(pdf.pages)
        any_text = False
        meta: dict[str, str] = {}
        meta_text: dict[str, dict] = {}  # verbatim header line each meta value came from
        results: list[RawResult] = []
        header_found = False

        pending: list[tuple] = []  # (page_rows, name_only) of the page just parsed
        for page_number, page in enumerate(pdf.pages, start=1):
            for rows_, names_ in pending:
                _join_wrapped_names(rows_, names_)
            pending = []
            words = page.extract_words(x_tolerance=1.5, keep_blank_chars=False)
            if words:
                any_text = True
            columns: list[tuple[str, float]] | None = None
            page_rows: list[tuple[float, float, list[RawResult]]] = []  # (top, name x0, results)
            name_only: list[tuple[float, float, str, list[float]]] = []  # (top, x0, text, bbox)
            pending.append((page_rows, name_only))
            for line in _group_lines(words):
                text = " ".join(w["text"] for w in line)
                header = _detect_header(line)
                if header:
                    columns = header
                    header_found = True
                    continue
                if columns is None:
                    acc = _ACCESSION_NO_COLON.match(text)
                    if acc and "accession" not in meta:
                        meta["accession"] = acc.group(1)
                        meta_text["accession"] = {"text": text, "page": page_number}
                    for key, value in _meta_from_line(text).items():
                        meta[key] = value
                        meta_text[key] = {"text": text, "page": page_number}
                    continue
                if _END_RE.match(text):
                    columns = None
                    skip("end_of_table_marker", page_number, text)
                    continue
                name_x = dict(columns)["test_name"]
                if line[0]["x0"] > name_x + 30:
                    skip("indented_comment", page_number, text)
                    if page_rows:  # keep it with the result it annotates (methods are often stated here)
                        for res in page_rows[-1][2]:
                            res.source_location.setdefault("comments", []).append(text)
                    continue  # indented comment or footnote under the previous result
                in_table_meta = _meta_from_line(text) or (
                    _meta_from_line(text, anchored=False) if "collected" in text.lower() else {}
                )
                if in_table_meta:
                    # "Fasting: Yes" or a panel heading "LIPID PANEL  Collected: ... Received: ..."
                    new_date = in_table_meta.get("collection_date")
                    if new_date and new_date != meta.get("collection_date"):
                        # A different collection event: earlier fasting status does not carry over.
                        meta.pop("conditions", None)
                        meta_text.pop("conditions", None)
                    for key, value in in_table_meta.items():
                        meta[key] = value
                        meta_text[key] = {"text": text, "page": page_number}
                    continue
                cells: dict[str, list[str]] = {k: [] for k, _ in columns}
                # Range-split tables right-align results, so a long word can start left of its
                # heading; place those by their centre instead of their left edge.
                range_split = "value" not in cells
                for w in line:
                    anchor = (w["x0"] + w["x1"]) / 2 if range_split else w["x0"] + 2
                    owner = columns[0][0]
                    for key, x0 in columns:
                        if anchor >= x0:
                            owner = key
                    cells[owner].append(w["text"])
                row = {k: " ".join(v) if v else None for k, v in cells.items()}
                if not row.get("test_name"):
                    skip("no_test_name", page_number, text)
                    continue
                method = meta.get("method")
                if range_split:
                    folded = _range_split_row(row)
                    if folded is None:
                        if all(not v for k, v in row.items() if k != "test_name"):
                            name_only.append((line[0]["top"], line[0]["x0"], text, [
                                min(w["x0"] for w in line), min(w["top"] for w in line),
                                max(w["x1"] for w in line), max(w["bottom"] for w in line)]))
                        skip("heading_wrap_comment_or_ambiguous", page_number, text)
                        continue  # section heading, wrapped name, or ambiguous row
                    row.update({k: v for k, v in folded.items() if k != "method"})
                    method = folded["method"] or method
                elif not row.get("value") and not row.get("unit"):
                    # Section heading such as "LIPID PANEL" - not a result.
                    skip("heading", page_number, text)
                    continue
                row_specimen = row.get("specimen")
                inherited = {k: v for k, v in meta_text.items() if not (k == "specimen" and row_specimen)}
                bbox = [
                    min(w["x0"] for w in line),
                    min(w["top"] for w in line),
                    max(w["x1"] for w in line),
                    max(w["bottom"] for w in line),
                ]
                prior = _prior_result(row.get("prior"))
                if prior is not None:
                    p_value, p_flag, p_date = prior
                    results.append(RawResult(
                        test_name=row["test_name"],
                        value=p_value,
                        unit=row.get("unit"),
                        flag=p_flag,
                        collection_date=p_date,
                        specimen=row_specimen or meta.get("specimen"),
                        specimen_source="row" if row_specimen else "report_header",
                        inherited_metadata={
                            **{k: v for k, v in inherited.items() if k in ("specimen", "collection_method")},
                            "unit": {"text": "Unit taken from the current-result cell on the same row", "page": page_number},
                        },
                        collection_method=meta.get("collection_method"),
                        reported_as="historical_in_later_report",
                        source_location={
                            "kind": "pdf_line", "page": page_number,
                            "bbox": [min(w["x0"] for w in line), min(w["top"] for w in line),
                                     max(w["x1"] for w in line), max(w["bottom"] for w in line)],
                            "page_width": float(page.width), "page_height": float(page.height),
                            "text": text, "column": "previous_result",
                        },
                    ))
                line_results: list[RawResult] = [results[-1]] if prior is not None else []
                results.append(
                    RawResult(
                        test_name=row["test_name"],
                        value=row.get("value"),
                        unit=row.get("unit"),
                        reference_range=row.get("reference_range"),
                        flag=row.get("flag"),
                        specimen=row_specimen or meta.get("specimen"),
                        specimen_source="row" if row_specimen else "report_header",
                        inherited_metadata=inherited,
                        accession=meta.get("accession"),
                        collection_date=meta.get("collection_date"),
                        report_date=meta.get("report_date"),
                        collection_method=meta.get("collection_method"),
                        laboratory=row.get("lab_code") or meta.get("laboratory"),
                        method=method,
                        conditions=meta.get("conditions"),
                        result_status=meta.get("result_status"),
                        source_location={
                            "kind": "pdf_line",
                            "page": page_number,
                            "bbox": bbox,
                            "page_width": float(page.width),
                            "page_height": float(page.height),
                            "text": text,
                        },
                    )
                )
                if range_split:
                    line_results.append(results[-1])
                    page_rows.append((line[0]["top"], line[0]["x0"], line_results))

        for rows_, names_ in pending:
            _join_wrapped_names(rows_, names_)

    if not any_text:
        return PdfParseResult(
            "no_text_layer",
            "This PDF has no extractable text (it may be a scanned image). OCR is not "
            "implemented; enter values manually while viewing the original.",
            page_count,
        )
    if not header_found:
        return PdfParseResult(
            "unsupported_layout",
            "No results table with recognizable column headings was found. Enter values "
            "manually while viewing the original.",
            page_count,
        )
    if not results:
        return PdfParseResult("unsupported_layout", "A results table was found but contained no rows.", page_count)
    return PdfParseResult("parsed", None, page_count, results)


def render_page_png(data: bytes, page_number: int, resolution: int = 110) -> bytes:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise IndexError(page_number)
        image = pdf.pages[page_number - 1].to_image(resolution=resolution).original
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
