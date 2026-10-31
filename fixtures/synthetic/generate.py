"""Generate the synthetic fixtures in this directory.

Every value here is invented. These files represent generic laboratory-report layouts,
not any specific vendor's format. Run inside the api-test image (needs reportlab):

    docker compose --profile test run --rm -v "$PWD/fixtures:/out" api-test \
        python /out/synthetic/generate.py /out/synthetic
"""

import csv
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)
BANNER = "SYNTHETIC TEST DATA - NOT A REAL PATIENT - GENERIC LAYOUT"


def write_csv(name: str, header: list[str], rows: list[list[str]]) -> None:
    with open(OUT / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# 1. Venous panel, ISO dates, clean.
write_csv(
    "synthetic_venous_panel_2022.csv",
    ["Test Name", "Result", "Units", "Reference Range", "Flag", "Collection Date", "Report Date",
     "Specimen", "Collection Method", "Lab", "Method", "Fasting"],
    [
        ["Cholesterol, Total", "214", "mg/dL", "<200", "H", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "", "Fasting 12h"],
        ["LDL Cholesterol (calculated)", "141", "mg/dL", "<100", "H", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "Martin-Hopkins", "Fasting 12h"],
        ["HDL Cholesterol", "48", "mg/dL", ">39", "", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "", "Fasting 12h"],
        ["Triglycerides", "126", "mg/dL", "<150", "", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "", "Fasting 12h"],
        ["Apolipoprotein B", "112", "mg/dL", "<90", "H", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "Immunoturbidimetric", "Fasting 12h"],
        ["Lipoprotein (a)", "88", "nmol/L", "<75", "H", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "", "Fasting 12h"],
        ["Hemoglobin A1c", "5.4", "%", "<5.7", "", "2022-05-10", "2022-05-12", "Whole blood", "Venipuncture", "SYNTHETIC Reference Lab A", "", ""],
        ["hs-CRP", "<0.3", "mg/L", "<1.0", "", "2022-05-10", "2022-05-12", "Serum", "Venipuncture", "SYNTHETIC Reference Lab A", "", ""],
    ],
)

# 2. Finger-prick (capillary) results, US numeric dates, different reference ranges and
#    an Lp(a) result in mass units.
write_csv(
    "synthetic_fingerprick_2023.csv",
    ["Biomarker", "Value", "Unit", "Ref Range", "Date Collected", "Sample Type", "Lab"],
    [
        ["Total Cholesterol", "205", "mg/dL", "125-200", "03/14/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
        ["LDL-C", "133", "mg/dL", "<130", "03/14/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
        ["HDL-C", "51", "mg/dL", "40-90", "03/14/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
        ["Lp(a)", "36", "mg/dL", "<30", "03/14/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
        ["Total Cholesterol", "198", "mg/dL", "125-200", "09/22/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
        ["LDL-C", "127", "mg/dL", "<130", "09/22/2023", "Dried blood spot", "SYNTHETIC Home Kit Lab"],
    ],
)

# 3. Edge cases: missing unit, ambiguous dates, two-digit year, unknown specimen,
#    non-numeric value, comparator value, unrecognized test name, missing date.
write_csv(
    "synthetic_edge_cases.csv",
    ["Analyte", "Result", "Units", "Collected", "Specimen", "Reference Interval"],
    [
        ["Triglycerides", "131", "", "2024-06-03", "Serum", "<150"],
        ["HDL Cholesterol", "50", "mg/dL", "04/06/2024", "Serum", ">39"],
        ["Total Cholesterol", "199", "mg/dL", "06/04/24", "", "<200"],
        ["Apolipoprotein B", "See note", "mg/dL", "2024-06-03", "Serum", "<90"],
        ["Analyte X-17", "4.2", "U/L", "2024-06-03", "Serum", "1-10"],
        ["Glucose", "92", "mg/dL", "", "Plasma", "65-99"],
        ["Lipoprotein (a)", "41", "mg/dL", "2024-06-03", "Specimen B", ""],
    ],
)

# 4. Layout this parser does not support.
write_csv("synthetic_unsupported_layout.csv", ["Patient", "Note"], [["SYNTHETIC-001", "Lipids normal per clinician"]])


# --- PDFs ----------------------------------------------------------------------

def lab_pdf(name: str, *, collected: str, reported: str, status: str | None, rows: list[tuple]) -> None:
    c = canvas.Canvas(str(OUT / name), pagesize=letter)
    c.setTitle("Synthetic laboratory report")
    y = 750
    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, y, BANNER)
    y -= 26
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "SYNTHETIC Reference Lab B")
    y -= 24
    c.setFont("Helvetica", 10)
    meta = [
        "Patient: SYNTHETIC-001",
        "Accession: SYN-B-240115-0117",
        f"Collected: {collected}",
        f"Reported: {reported}",
        "Specimen: Serum",
        "Collection Method: Venipuncture",
        "Laboratory: SYNTHETIC Reference Lab B",
        "Fasting: Yes",
    ]
    if status:
        meta.append(f"Report Status: {status}")
    for line in meta:
        c.drawString(50, y, line)
        y -= 15
    y -= 12
    cols = [50, 250, 320, 360, 440]
    c.setFont("Helvetica-Bold", 10)
    for x, label in zip(cols, ["Test", "Result", "Flag", "Units", "Reference Range"]):
        c.drawString(x, y, label)
    y -= 18
    c.setFont("Helvetica", 10)
    for row in rows:
        if len(row) == 1:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, row[0])
            c.setFont("Helvetica", 10)
        else:
            for x, cell in zip(cols, row):
                if cell:
                    c.drawString(x, y, cell)
        y -= 16
    y -= 10
    c.drawString(50, y, "End of report")
    c.save()


BASE_ROWS = [
    ("LIPID PANEL",),
    ("Cholesterol, Total", "209", "H", "mg/dL", "<200"),
    ("LDL Cholesterol (calculated)", "131", "H", "mg/dL", "<100"),
    ("HDL Cholesterol", "52", "", "mg/dL", ">39"),
    ("Triglycerides", "118", "", "mg/dL", "<150"),
    ("Non-HDL Cholesterol", "157", "H", "mg/dL", "<130"),
    ("CARDIOMETABOLIC",),
    ("Apolipoprotein B", "104", "H", "mg/dL", "<90"),
    ("Lipoprotein(a)", "92", "H", "nmol/L", "<75"),
    ("Hemoglobin A1c", "5.5", "", "%", "<5.7"),
]
lab_pdf("synthetic_lab_report_2024.pdf", collected="2024-01-15", reported="2024-01-17", status="Final", rows=BASE_ROWS)
lab_pdf(
    "synthetic_lab_report_2024_corrected.pdf",
    collected="2024-01-15",
    reported="2024-01-19",
    status="CORRECTED",
    rows=[r if r[0] != "LDL Cholesterol (calculated)" else ("LDL Cholesterol (calculated)", "127", "H", "mg/dL", "<100")
          for r in BASE_ROWS],
)


def scanned_pdf(name: str) -> None:
    img = Image.new("RGB", (850, 1100), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 60), BANNER, fill="black")
    d.text((60, 100), "SCANNED IMAGE - NO TEXT LAYER", fill="black")
    d.text((60, 160), "Cholesterol, Total    201   mg/dL   <200", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c = canvas.Canvas(str(OUT / name), pagesize=letter)
    c.drawImage(ImageReader(buf), 0, 0, width=612, height=792)
    c.save()


def letter_pdf(name: str) -> None:
    c = canvas.Canvas(str(OUT / name), pagesize=letter)
    c.setFont("Helvetica", 11)
    y = 740
    for line in [BANNER, "", "Dear SYNTHETIC-001,", "Your recent cholesterol results were reviewed.",
                 "Total cholesterol was 201 and we discussed diet.", "Sincerely, Synthetic Clinic"]:
        c.drawString(60, y, line)
        y -= 18
    c.save()


def range_split_pdf(name: str, *, previous_column: bool) -> None:
    """Generic range-split layout: In Range / Out of Range columns, unit inside the reference
    cell, per-panel Collected lines, indented comments, optional previous-result column."""
    if previous_column:
        cols = {"name": 42, "in": 181, "out": 235, "ref": 330, "prev": 420, "lab": 550}
        heads = [("TEST NAME", "name"), ("IN RANGE", "in"), ("OUT OF RANGE", "out"),
                 ("REFERENCE RANGE", "ref"), ("PREVIOUS RESULT AND DATE", "prev"), ("LAB", "lab")]
    else:
        cols = {"name": 42, "in": 264, "out": 352, "ref": 450, "lab": 548}
        heads = [("TEST NAME", "name"), ("IN RANGE", "in"), ("OUT OF RANGE", "out"),
                 ("REFERENCE RANGE", "ref"), ("LAB", "lab")]
    # (name, in-range value, out-of-range value, flag, reference range, unit, previous)
    pages = [
        [
            ("panel", "LIPID PANEL, STANDARD", "03/04/2025 07:35 EST", "03/04/2025 12:10 EST"),
            ("meta", "Fasting: YES"),
            ("row", "CHOLESTEROL, TOTAL", "", "212", "H", "<200", "mg/dL", "198 02/10/2024"),
            ("row", "HDL CHOLESTEROL", "55", "", "", "> OR = 40", "mg/dL", "51 02/10/2024"),
            ("row", "TRIGLYCERIDES", "101", "", "", "<150", "mg/dL", ""),
            ("row", "LDL-CHOLESTEROL", "", "134", "H", "", "mg/dL (calc)", "121 02/10/2024"),
            ("note", "Reference range: <100"),
            ("note", "Desirable range <100 mg/dL for primary prevention; <70 mg/dL for patients"),
            ("note", "with CHD or diabetic patients with > or = 2 CHD risk factors."),
            ("row", "NON HDL CHOLESTEROL", "", "157", "H", "<130", "mg/dL (calc)", ""),
            ("panel", "APOLIPOPROTEIN B", "03/04/2025 07:35 EST", "03/04/2025 12:10 EST"),
            ("row", "APOLIPOPROTEIN B", "", "108", "H", "<90", "mg/dL", "99 02/10/2024"),
            ("subrow", "LDL PARTICLE NUMBER", "", "1650", "H", "<1138", "nmol/L", ""),
            ("note", "Risk: Optimal <90 mg/dL; Moderate 90-129 mg/dL; High >129 mg/dL"),
        ],
        [
            ("panel", "LIPOPROTEIN (a)", "03/06/2025 09:15 EST", "03/06/2025 13:40 EST"),
            ("row", "LIPOPROTEIN (a)", "", "88", "H", "<75", "nmol/L", ""),
            ("panel", "HEMOGLOBIN A1c", "03/04/2025 07:35 EST", "03/04/2025 12:10 EST"),
            ("row", "HEMOGLOBIN A1c", "5.4", "", "", "<5.7", "%", "5.5 02/10/2024"),
            ("panel", "URINALYSIS, COMPLETE", "03/04/2025 07:35 EST", "03/04/2025 12:10 EST"),
            ("row", "GLUCOSE", "NEGATIVE", "", "", "NEGATIVE", "", ""),
            ("panel", "THYROID ANTIBODIES", "03/04/2025 07:35 EST", "03/04/2025 12:10 EST"),
            ("prefix", "THYROID PEROXIDASE"),
            ("row", "ANTIBODIES", "<1", "", "", "<9", "IU/mL", ""),
            ("row", "SEX HORMONE BINDING", "", "54", "H", "10-50", "nmol/L", ""),
            ("cont", "GLOBULIN"),
        ],
    ]
    # A second table style on its own page: "OUT RANGE" heading, reference printed left of its
    # heading (inside the result column), and a comment that starts at the left margin.
    shifted = [
        ("HS CRP", "0.8", "<1.0", "mg/L"),
        ("INSULIN", "6.1", "<=18.4", "uIU/mL"),
    ]
    # In-range results whose reference text starts inside the out-of-range column.
    overlapping = [("CREATININE", "0.92", "0.60-1.29 mg/dL (calc)"), ("VITAMIN D, 25-OH, TOTAL", "41", "30-100 ng/mL")]
    c = canvas.Canvas(str(OUT / name), pagesize=letter)
    c.setTitle("Synthetic range-split laboratory report")
    for page_no, rows in enumerate(pages, start=1):
        c.setFont("Helvetica-Bold", 8)
        c.drawString(42, 770, BANNER)
        c.setFont("Helvetica", 8)
        header = [
            (42, 748, "Patient Name: SYNTHETIC, PATIENT"),
            (206, 736, "Collection Date: 03/04/2025 07:35 EST"),
            (206, 714, "Date Reported: 03/07/2025 16:02 EST"),
            (206, 692, "Received: 03/04/2025 12:10 EST"),
            (206, 670, "Accession Number: SYNRS0000001"),
            (206, 648, "Lab Ref #: 000000"),
            (275, 760, "Report Status: FINAL"),
        ]
        for x, y, text in header:
            c.drawString(x, y, text)
        y = 600
        c.setFont("Helvetica-Bold", 8)
        for label, key in heads:
            c.drawString(cols[key], y, label)
        y -= 26
        for row in rows:
            kind = row[0]
            if kind == "panel":
                c.setFont("Helvetica-Bold", 8)
                c.drawString(42, y, row[1])
                c.setFont("Helvetica", 7)
                c.drawString(cols["name"] + 175, y, f"Collected: {row[2]}  Received: {row[3]}")
                y -= 13
            elif kind == "meta":
                c.setFont("Helvetica", 8)
                c.drawString(42, y, row[1])
                y -= 13
            elif kind in ("prefix", "cont"):
                # A wrapped test name: same x as result names, closer than the row spacing.
                c.setFont("Helvetica", 8)
                if kind == "cont":
                    y += 2
                c.drawString(46, y, row[1])
                y -= 10
            elif kind == "note":
                c.setFont("Helvetica", 7)
                c.drawString(80, y, row[1])
                y -= 10
            else:
                _, test, inv, outv, flag, ref, unit, prev = row
                c.setFont("Helvetica", 8)
                c.drawString(46 if kind == "row" else 63, y, test)  # subrows sit 21pt in
                if inv:
                    c.drawRightString(cols["in"] + 30, y, inv)
                if outv:
                    c.drawRightString(cols["out"] + 55, y, outv)
                    if flag:
                        c.drawString(cols["out"] + 70, y, flag)
                ref_text = " ".join(t for t in (ref, unit) if t)
                if ref_text:
                    c.drawString(cols["ref"], y, ref_text)
                if previous_column and prev:
                    c.drawString(cols["prev"], y, prev)
                c.drawString(cols["lab"] + 5, y, "SY1")
                y -= 12
        c.setFont("Helvetica", 7)
        c.drawString(539, 30, f"Page {page_no} of {len(pages) + 1}")
        c.showPage()
    c.setFont("Helvetica-Bold", 8)
    c.drawString(42, 770, BANNER)
    c.drawString(206, 736, "Collection Date: 03/04/2025 07:35 EST")
    for x, label in ((39, "ANALYTE NAME"), (227, "IN RANGE"), (294, "OUT RANGE"), (404, "REFERENCE RANGE"), (553, "LAB")):
        c.drawString(x, 600, label)
    c.setFont("Helvetica", 8)
    y = 580
    for test, value, ref, unit in shifted:
        c.drawString(39, y, test)
        c.drawRightString(319, y, value)
        c.drawString(353, y, f"{ref} {unit}")
        c.drawString(552, y, "SY2")
        y -= 16
        c.setFont("Helvetica", 7)
        c.drawString(39, y, "This test was developed and its performance characteristics determined by the laboratory 1 2 3.")
        c.setFont("Helvetica", 8)
        y -= 16
    for test, value, ref in overlapping:
        c.drawString(39, y, test)
        c.drawRightString(250, y, value)
        c.drawString(300, y, ref)
        c.drawString(552, y, "SY2")
        y -= 16
    c.setFont("Helvetica", 7)
    c.drawString(539, 30, f"Page {len(pages) + 1} of {len(pages) + 1}")
    c.showPage()
    c.save()


range_split_pdf("synthetic_range_split_report.pdf", previous_column=False)
range_split_pdf("synthetic_range_split_with_previous.pdf", previous_column=True)


scanned_pdf("synthetic_scanned_image_only.pdf")
letter_pdf("synthetic_unsupported_letter.pdf")
print("fixtures written to", OUT)
