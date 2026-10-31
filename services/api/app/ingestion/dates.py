"""Date parsing that refuses to guess.

A numeric date like 03/04/2023 is ambiguous (March 4 or April 3) unless the
participant declared the document's date order at upload. Two-digit years are
ambiguous by century. Ambiguous and unparseable dates yield no date value.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}

_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")
_NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})(?:\s+.*)?$")
_MON_D_Y = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")
_D_MON_Y = re.compile(r"^(\d{1,2})[\s-]([A-Za-z]+)\.?[\s-](\d{4})$")


@dataclass(frozen=True)
class ParsedDate:
    value: date | None
    status: str  # exact | ambiguous | missing | unparseable
    interpretation: str | None = None  # how an exact value was obtained, when not self-evident


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(raw: str | None, declared_order: str | None = None) -> ParsedDate:
    if raw is None or not raw.strip():
        return ParsedDate(None, "missing")
    s = raw.strip()

    if m := _ISO.match(s):
        d = _make(int(m[1]), int(m[2]), int(m[3]))
        return ParsedDate(d, "exact") if d else ParsedDate(None, "unparseable")

    for pattern, order in ((_MON_D_Y, "mdy"), (_D_MON_Y, "dmy")):
        if m := pattern.match(s):
            mon_s, day_s = (m[1], m[2]) if order == "mdy" else (m[2], m[1])
            month = MONTHS.get(mon_s.lower())
            if month is None:
                return ParsedDate(None, "unparseable")
            d = _make(int(m[3]), month, int(day_s))
            return ParsedDate(d, "exact") if d else ParsedDate(None, "unparseable")

    if m := _NUMERIC.match(s):
        a, b, y_s = int(m[1]), int(m[2]), m[3]
        if len(y_s) == 2:
            return ParsedDate(None, "ambiguous", "two_digit_year")
        y = int(y_s)
        if a > 12 and b > 12:
            return ParsedDate(None, "unparseable")
        if a > 12:
            d = _make(y, b, a)
            return ParsedDate(d, "exact", "day_first_unambiguous") if d else ParsedDate(None, "unparseable")
        if b > 12:
            d = _make(y, a, b)
            return ParsedDate(d, "exact", "month_first_unambiguous") if d else ParsedDate(None, "unparseable")
        if a == b:
            d = _make(y, a, b)
            return ParsedDate(d, "exact") if d else ParsedDate(None, "unparseable")
        if declared_order == "MDY":
            d = _make(y, a, b)
            return ParsedDate(d, "exact", "declared_order_MDY") if d else ParsedDate(None, "unparseable")
        if declared_order == "DMY":
            d = _make(y, b, a)
            return ParsedDate(d, "exact", "declared_order_DMY") if d else ParsedDate(None, "unparseable")
        return ParsedDate(None, "ambiguous", "month_day_order_unknown")

    try:
        return ParsedDate(datetime.fromisoformat(s).date(), "exact")
    except ValueError:
        return ParsedDate(None, "unparseable")
