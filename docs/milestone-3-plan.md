# Milestone 3: Risk investigation

Brief §14: "Eligibility-aware reference calculation, hypothesis records, and evidence ledger.
Acceptance: calculations match reference cases; claims expose their evidence and status."

Started 2026-10-21 at the participant's request. Acceptance criteria below were written before
implementation (brief §14: the agent must not weaken them to make its own work pass).

## Scope, in order

**3A. Reference risk calculation (PREVENT base model).** 10-year and 30-year total CVD, ASCVD
and heart failure, base model only (no HbA1c, UACR or SDI variants yet).
**3B. Personal profile inputs.** Facts the labs do not contain, entered and audited.
**3C. Hypothesis records and evidence ledger.** Private, in the records database. Not started.

Out of scope: recommendations, forecasts (Milestone 4), experiments (Milestone 5), PCE/other models.

## Sources

| Source | Role | Status |
|---|---|---|
| Khan SS et al. *Circulation* 2024;149:430-449 (PMID 37947085, PMC10910659), Supplemental Tables | Authoritative coefficients and input ranges | **Blocked:** PMC serves the supplement behind a CAPTCHA to scripts; Europe PMC 403 (not open access); legacy NCBI path 404. Needs a person to download it. |
| Erratum, 2026-10-14 (doi:10.1161/CIRCULATIONAHA.123.067626) | Swaps HbA1c terms in the HbA1c/full models | Not relevant to the base model; recorded so the HbA1c variant is never implemented without it. |
| AHA PREVENT online calculator (professional.heart.org) | Authoritative reference outputs | **Done 2026-10-21:** 14 synthetic profiles entered by browser automation, 84 displayed outputs saved in `tests/risk/data/aha_calculator_reference_cases.json`. The engine matches all of them to the displayed precision. |
| `preventr` 0.12.1 (CRAN, MIT license, M. Mayer) | Independent implementation for cross-checking; coefficient transcription to compare against the supplement | Downloaded to `~/cardio-sources/prevent/` (outside the repo). Not authoritative. |

Licensing (D-006): the equations are published; this implementation is for personal use and is
written from the published coefficients. Commercial use of PREVENT remains an open question. AHA's licensed source code is not used.

## Acceptance criteria (fixed 2026-10-21)

3A is accepted only when all of these hold:

1. **Reference cases.** For at least 12 synthetic profiles (both sexes; both horizons; ages 30,
   45, 59, 60, 79; each binary input on and off; values at range boundaries), every output
   matches the AHA calculator or the supplement's worked examples at the precision those sources
   display. Until such outputs exist, 3A is reported as **not accepted**, whatever else passes.
2. **Coefficients from the authoritative source.** Every coefficient equals the supplement value.
   The `preventr` transcription is compared against it; any difference is reported, not resolved
   by choosing one silently.
3. **Implementation agreement (secondary).** Agrees with `preventr` 0.12.1 to within 1e-9 on the
   unrounded probability across at least 1,000 random in-range profiles. This shows two
   implementations agree; it is not validation.
4. **Eligibility, no extrapolation.** Age outside 30-79 (10-year) or 30-59 (30-year), or any input
   outside its published range, or any missing required input, yields no estimate and a stated
   reason. No imputation, no clamping. One test per boundary, both sides.
5. **Inputs only through the calculation boundary.** Laboratory inputs come only from
   `calc_inputs.py`. Unverified, flagged, superseded or blocked values cannot be used (tests).
6. **Recorded, immutable results.** Each result stores the equation and coefficient-source
   version, every input value with its observation ID or profile-entry ID and date, the
   eligibility decision, each input's `verification_method`, and the code version. Stored results
   cannot be updated (database trigger) and are recomputable from what they store.
7. **Honest labels.** A result whose inputs include an automated-check acceptance says so. Every
   result states that it is a population reference estimate, not a personal risk explanation, and
   that a change in the estimate is not evidence that disease risk changed.
8. **Input timing.** The most recent eligible value of each input is used, its date shown; if the
   inputs span more than 365 days the result carries a stated warning. (Decision recorded.)

3B is accepted when profile facts (sex, date of birth, SBP readings, height/weight, diabetes,
smoking, BP medication, statin) are entered through the app, audited, versioned, and used only
through the same boundary.

## Known consequences

- Laboratory reports contain no blood pressure. Until SBP readings are entered, no estimate exists.
- If the participant is under 30, PREVENT produces no estimate by design; the result says so.
- Brief Gate A requires every calculation input to be checked against its source. Inputs accepted
  by automated check (D-038) were checked for transcription by software, not by a person; results
  carry that label.

## Status (2026-10-21)

| Criterion | Status |
|---|---|
| 1 Reference cases | **Met.** 14 profiles, 84 outputs, all within half a display unit (`tests/risk/test_reference_cases.py`). |
| 2 Coefficients vs supplement | **Met (2026-10-21).** Official supplement (2025-09-25 file from the 2026-10-14 correction) obtained; 0 coefficient differences; worked examples match to <1e-12. Input ranges corrected to the official ones. See `docs/prevent-versioning.md`. |
| 3 Agreement with preventr | **Met.** Max difference < 1e-9 over 1,920 profile-horizons x 3 outcomes. |
| 4 Eligibility | **Met in the engine** (boundary tests both sides). |
| 5-8 Boundary, stored results, labels, timing | **Not started** (needs 3B profile inputs and the results table). |
