# Synthetic fixtures

Every value is invented. Layouts are generic and do not represent any specific vendor (no
Function Health compatibility is claimed). Regenerate with `make fixtures`.

| File | Purpose |
|---|---|
| synthetic_venous_panel_2022.csv | Clean venous panel, ISO dates, all columns, comparator value (`<0.3`) |
| synthetic_fingerprick_2023.csv | Capillary (dried blood spot), US numeric dates, different reference ranges, Lp(a) in mg/dL |
| synthetic_edge_cases.csv | Missing unit, ambiguous dates, two-digit year, unknown specimen, non-numeric value, unrecognized test, missing date |
| synthetic_unsupported_layout.csv | Header without test/result columns |
| synthetic_lab_report_2024.pdf | Text-layer PDF with section headings and report-level metadata |
| synthetic_lab_report_2024_corrected.pdf | Same draw, "Report Status: CORRECTED", one changed value |
| synthetic_scanned_image_only.pdf | Image-only PDF (no text layer) |
| synthetic_unsupported_letter.pdf | Text PDF with no results table |
