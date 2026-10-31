# Validation plan

Acceptance criteria are fixed before implementation. Do not weaken them to make an
implementation pass; propose changes in `docs/decisions.md` and get participant approval.

## Milestone 1–2 acceptance criteria (as set by the participant, 2026-10-20)

| # | Criterion | How it is checked | Status |
|---|---|---|---|
| 1 | A clean checkout starts using documented commands | Copy of repository without build artifacts, `make up`, health + page load | Passed 2026-10-20 (see current-state.md) |
| 2 | Upload, extraction, source review, correction, acceptance and longitudinal display complete | `make e2e` (Playwright) | Passed |
| 3 | Missing units tested | `test_missing_units_block_acceptance`, e2e step 3 | Passed |
| 4 | Ambiguous dates tested | `test_parse_date_never_guesses`, `test_ambiguous_dates_stay_unknown_and_block`, `test_declared_date_order_resolves_numeric_dates`, e2e step 4 | Passed |
| 5 | Duplicate reports tested | `test_duplicate_report_is_flagged_not_merged`, `test_invalid_resolution_rejected` | Passed |
| 6 | Corrected results tested | `test_correction_preserves_previous_value_and_writes_audit`, `test_lab_corrected_report_is_linked_only_after_confirmation`, e2e step 5 | Passed |
| 7 | Unknown specimen types tested | `test_unknown_specimen_type_is_preserved_as_unknown` | Passed |
| 8 | Differing reference ranges tested | `test_differing_reference_ranges_are_kept_per_point_and_noticed` | Passed |
| 9 | Unverified observations excluded from downstream inputs | `tests/safety/test_calculation_input_boundary.py` (4 tests), e2e final check; mutation-checked | Passed |
| 10 | Backup-and-restore test | `make restore-test` (plaintext and encrypted) | Passed |
| 11 | Automated tests and browser-level test executed | `make test`, `make e2e` | Passed |
| 12 | Capillary and venous distinguishable | `test_capillary_and_venous_are_separate_series`, `test_capillary_and_venous_same_day_are_not_flagged_as_duplicates`, e2e step 7–8 | Passed |
| 13 | Unsupported layouts / image-only PDFs show a limitation and manual path | `test_image_only_pdf_...`, `test_unsupported_layouts_...`, e2e step 6 | Passed |
| 14 | No real records in repo, logs or telemetry | `test_no_health_data_in_logs.py`; `.gitignore`; synthetic fixtures only | Passed for code paths tested; see limitations |

## Brief gates and their status

### Gate A — Record integrity
Covered for synthetic generic layouts: wrong/ambiguous dates, duplicate reports, corrected
results, missing units, unknown specimen types, changed reference ranges, conflicting
measurements, ambiguous extraction. A release fails if an unresolved extraction error can enter
calculation inputs silently; this is enforced by the boundary tests.

**Outstanding (Gate A):**
- Test against at least one actual, redacted laboratory report from each real source (e.g.
  a consumer lab-testing export and older finger-prick reports). Until then, no vendor
  compatibility is claimed. Procedure: participant redacts identifiers, runs the import locally,
  records parse status and every extraction error in `docs/current-state.md`; fixes are made
  against a synthetic reproduction of the layout, never against the real file in agent context.
- A manually checked test set covering realistic report formats (brief §12, Gate A).
- For the personal pilot: every measurement used in a calculation must have been checked against
  its source. The acceptance step enforces this procedurally; it does not prove the participant
  checked carefully.

### Gate B — Computational correctness
Not started (Milestone 3+). Requires PREVENT licensing and authoritative reference outputs
(decision D-006).

### Gates C–E
Not started. Prerequisites: observation workflow (Milestone 4), experiment workflow (Milestone 5).

## Withheld tests

The brief requires a small set of tests withheld from the implementing agent. None exist yet:
everything in `tests/` was written by the same agent that wrote the implementation. **Outstanding:**
the participant (or a separate reviewer) should author withheld ingestion cases, for example new
synthetic layouts and adversarial date/unit cases, and run them without sharing them with the
coding agent.

## Overnight queue acceptance (2026-10-21)

| # | Criterion | How it is checked | Status |
|---|---|---|---|
| Q1A | Header specimen not applied silently; HbA1c/serum regression surfaced and blocked; unknown stays unknown | `tests/records/test_specimen_provenance.py` (9 tests), e2e step 2b | Passed |
| Q1B | Corrected values recognised as possible replacements using accession/event context; repeats not merged; no double counting | `tests/records/test_collection_events.py` (7 tests), e2e match-basis check | Passed |
| Q1C | Destructive operations only target disposable projects | `make guard-test`; all destructive scripts route through `disposable_down` | Passed |
| Q2 | Validated evidence-record and research-question format | `tests/research/test_evidence_validation.py` (17 tests incl. mutation tests) | Passed |
| Q3 | Three entries verified against full text; chart inputs with source locations | `make research-validate SOURCE_CACHE=…` (62 claims, 40 chart rows, quotes checked verbatim) | Passed (see current-state for run) |
| Q4 | Notebook separate from records; findings vs uncertainty vs project connection vs data needed vs not concluded | `tests/end-to-end/notebook.spec.ts` | Passed (see current-state) |
| Q5 | Chart values equal stored inputs; links and sources accessible; desktop and mobile usable; no private paths/credentials/logs | `tests/end-to-end/notebook.spec.ts`, records mobile step in `workflow.spec.ts` | Passed (see current-state) |

These are internal automated checks written by the implementing agent. A separate automated
reviewer agent challenged the research entries (see current-state); that is not independent
or clinical review.
