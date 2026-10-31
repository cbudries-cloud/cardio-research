"""CSV laboratory-result parser.

Supported layout: one result per row, a header row naming at least a test-name column
and a value column. Column names are matched against the synonyms below. Anything else
is reported as an unsupported layout so the participant can enter values manually.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from app.ingestion.candidate import RawResult

PARSER_NAME = "csv_generic"
PARSER_VERSION = "1"

COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "test_name": ("test", "test name", "analyte", "component", "biomarker", "marker", "name"),
    "value": ("result", "value", "result value"),
    "unit": ("unit", "units", "uom"),
    "collection_date": ("collection date", "collected", "date collected", "draw date",
                        "specimen collection date", "collection_date"),
    "report_date": ("report date", "reported", "date reported", "result date", "report_date"),
    "specimen": ("specimen", "specimen type", "sample type", "sample"),
    "collection_method": ("collection method", "collection type", "draw method"),
    "reference_range": ("reference range", "ref range", "reference interval", "range", "normal range"),
    "flag": ("flag", "abnormal flag", "status flag"),
    "laboratory": ("lab", "laboratory", "performing lab"),
    "method": ("method", "assay", "methodology"),
    "conditions": ("fasting", "conditions", "collection conditions"),
    "result_status": ("result status", "status", "report status"),
    "accession": ("accession", "accession number", "accession id", "accession no", "specimen id", "requisition"),
}
_SYNONYM_INDEX = {syn: key for key, syns in COLUMN_SYNONYMS.items() for syn in syns}


def _norm_header(h: str) -> str:
    return " ".join(re.sub(r"[_\-]+", " ", h.strip().lower().lstrip("﻿")).split())


@dataclass
class CsvParseResult:
    status: str
    message: str | None
    results: list[RawResult] = field(default_factory=list)


def parse_csv(data: bytes) -> CsvParseResult:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            return CsvParseResult("unsupported_layout", "File is not readable text.")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return CsvParseResult("unsupported_layout", "File is empty.")

    header = rows[0]
    mapping: dict[int, str] = {}
    unmapped: list[str] = []
    for i, h in enumerate(header):
        key = _SYNONYM_INDEX.get(_norm_header(h))
        if key and key not in mapping.values():
            mapping[i] = key
        elif h.strip():
            unmapped.append(h.strip())
    if "test_name" not in mapping.values() or "value" not in mapping.values():
        return CsvParseResult(
            "unsupported_layout",
            "Header row does not contain recognizable test-name and result columns. "
            "Enter values manually from the original file.",
        )

    results: list[RawResult] = []
    skipped = 0
    for row_index, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        fields: dict[str, str | None] = {}
        for col, key in mapping.items():
            fields[key] = row[col] if col < len(row) else None
        name = (fields.get("test_name") or "").strip()
        if not name:
            skipped += 1
            continue
        results.append(
            RawResult(
                test_name=name,
                value=fields.get("value"),
                unit=fields.get("unit"),
                collection_date=fields.get("collection_date"),
                report_date=fields.get("report_date"),
                specimen=fields.get("specimen"),
                collection_method=fields.get("collection_method"),
                reference_range=fields.get("reference_range"),
                flag=fields.get("flag"),
                laboratory=fields.get("laboratory"),
                method=fields.get("method"),
                conditions=fields.get("conditions"),
                result_status=fields.get("result_status"),
                accession=fields.get("accession"),
                source_location={
                    "kind": "csv_row",
                    "row_number": row_index,
                    "header": header,
                    "cells": row,
                },
            )
        )

    notes = []
    if skipped:
        notes.append(f"{skipped} row(s) without a test name were skipped.")
    if unmapped:
        notes.append("Columns not imported: " + ", ".join(unmapped) + ".")
    if not results:
        return CsvParseResult("unsupported_layout", "No result rows found. " + " ".join(notes))
    status = "parsed_with_issues" if skipped else "parsed"
    return CsvParseResult(status, " ".join(notes) or None, results)
