# PREVENT: source version, implemented variants and verification status (2026-10-21)

## 1. Authoritative source and its versions

| Item | Value |
|---|---|
| Equations | Khan SS et al. Development and Validation of the American Heart Association's PREVENT Equations. *Circulation* 2024;149(6):430-449. doi:10.1161/CIRCULATIONAHA.123.067626, PMID 37947085 |
| Correction 1 | *Circulation* 2024;149(11):e956, doi:10.1161/CIR.0000000000001230 (PMID 38466792). Text: an SDI data year range changed from 2015-2020 to 2015-2019. No coefficient change. |
| Correction 2 | *Circulation* 2026-10-14, doi:10.1161/CIR.0000000000001491 (PMID 42872321). Text: in Table 3 ("Glycemic Status") and supplement tabs S3, S10, S12C (A1c 10 yr), S12E (Full 10 yr), S12H (A1c 30 yr), S12J (Full 30 yr), the row headers "HbA1c no DM, per 1%" and "HbA1c in DM, per 1%" were inverted. Updated supplement: `supplement-tables-for-manuscript_withcalc_20260925.xlsx`. |
| Supplement used | That 2025-09-25 file, downloaded 2026-10-21 from the correction page (browser; the publisher blocks scripted access). SHA-256 recorded in `services/api/app/risk/prevent_base_coefficients.json`. Kept outside the repository (`~/cardio-sources/prevent/`). |

**Does the implementation include the 2026-10-14 correction?** It does not need to: the
correction changes only HbA1c-containing variants (HbA1c and full models), which are **not
implemented**. The base model's tables (S12A, S12F) are unaffected and were compared against the
corrected file. If an HbA1c variant is ever implemented, it must be built from the corrected tabs;
`preventr` 0.12.1 already swaps the two terms, which agrees with the correction text, but that is a
third-party transcription.

## 2. Implemented variants

PREVENT **base** model only: 10-year and 30-year total CVD, ASCVD and heart failure, women and men.
Not implemented: UACR, HbA1c, SDI and full variants; the CHD and stroke columns present in the
supplement; PCE.

## 3. Eligibility rules (from supplement "Allowable range", S12A/S12F)

Age 30-79 (10-year); age 30-59 (30-year, from the paper text and the online calculator, which
shows no 30-year estimate at 60+; **discrepancy**: the S12F sheet prints "30-79"). Total cholesterol
130-320 mg/dL; HDL-C 20-100 mg/dL; SBP 90-200 mm Hg; BMI 18.5 to <40 kg/m²; eGFR 15-150; binary
inputs 0/1. Missing or out-of-range inputs make the affected outcome ineligible; nothing is
imputed or clamped. BMI is required only for heart failure (it has zero coefficients elsewhere).

**Corrected 2026-10-21:** the first implementation copied `preventr`'s ranges (SBP 90-180, eGFR
15-140, BMI 18.5-39.9). The official ranges are wider; the engine now uses them.

## 4. Numerical verification (separate from source and licensing)

| Check | Result |
|---|---|
| Coefficients vs official supplement S12A/S12F | 0 differences (23 + 24 terms x 2 sexes x 3 outcomes) |
| Official worked examples (S12A, S12F) | Match to < 1e-12, both sexes, all outcomes and horizons |
| AHA online calculator, 14 synthetic profiles, 84 displayed outputs | All within half a display unit |
| `preventr` 0.12.1, 1,920 random profile-horizons | Max difference < 1e-9 (implementation agreement only) |

## 5. Source and licensing verification

- Coefficients now trace to the authoritative supplement; `preventr` (MIT) is no longer the
  coefficient source of record, only a cross-check.
- AHA distributes PREVENT source code under a license agreement; that code is **not** used. This
  implementation is written from the published equations for personal, non-commercial use.
  Whether commercial use requires a license is **unresolved**.
- The supplement file itself is the publisher's; it is not redistributed in this repository.

## 6. Remaining verification gaps

- The 30-year age-range discrepancy in S12F (resolved conservatively as 30-59).
- No independent (non-agent) review of the implementation.
- Profile inputs (age, sex, SBP, smoking, diabetes, medications, BMI) do not exist yet, so the
  engine has not been run on the participant's record.
