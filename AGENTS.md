# AGENTS.md — instructions for coding agents

Read this file, `docs/current-state.md`, and `docs/safety-boundaries.md` before changing anything.
The product brief is `docs/product-brief.md`; decisions are in `docs/decisions.md`.

## Active milestone

**Research partner, end to end (D-056, 2026-10-27):** cardiovascular overview (`/`), questions over the
record (`/ask`), research priorities and versioned investigations (`/research`), next investigation and
preserved predictions (`/next`), self-reported context (`/context`). The ApoB/LDL-P review (`/investigation`)
is one investigation within it. See `docs/current-state.md`.

## Prohibited functionality

- Prescribing, starting, stopping or adjusting medication or supplements; ordering tests; diagnosis.
- Numerical personal risk statements, except a future PREVENT estimate from complete, entered inputs.
- Starting or scheduling an experiment autonomously. Protocols are drafts; a prediction is preserved only
  when the participant locks it (D-061).
- A personalized forecast from two laboratory values, or treating a biomarker forecast as proof of health.
- Interpreting a laboratory flag as a risk assessment or diagnosis. A lab flag is stored as text.
- Unit conversions or lab-to-lab correction factors (decision D-011).
- Any code path that lets an observation reach calculation inputs without explicit acceptance.
- Calls to external AI/LLM services except one approved live run at a time (D-050, D-059): prepared from
  accepted observations with their status, scrub-checked, and sent only after the participant approves that
  exact request. Parsing, verification and snapshots must work without credentials.
- Public searches containing anything from a record (D-057): queries are code constants.
- Notes, hypotheses or prior model output becoming facts without explicit participant acceptance (D-060).
- Authentication, multi-user features, billing, analytics, telemetry or crash reporting.
- Publishing ports on anything other than 127.0.0.1, or deploying remotely.
- Publishing the notebook, connecting it to the records API/database, or setting any research
  question's personal applicability to anything but `not_assessed` (D-031, D-032).
- Adding research numbers that are not in a claim with a verbatim source quote, or chart values not
  generated from claims (`make research-charts`). Never reconstruct values from figure images.

## Sensitive data

- Develop and test with `fixtures/synthetic/` only. Never add real records, real report
  screenshots or real backups to the repository, prompts, issue trackers, or test output.
- Real records live only in Docker volumes and in backups outside the repo
  (`~/cardio-research-data/backups` by default). Do not read them while developing.
- Never log observation values, test names, file names or exception messages. Use
  `app.logging_safe`. `tests/safety/test_no_health_data_in_logs.py` enforces this.
- If a bug needs a real document to reproduce, ask the participant for a redacted or
  synthetic reproduction instead.

## Required tests

Every change must keep these green, and they must actually be executed (do not report a
test as passing without running it):

| Command | What it covers |
|---|---|
| `make test` | API unit and integration tests (pytest, isolated `cardio_test` database) |
| `make e2e` | Browser-level workflow test (Playwright, isolated stack) |
| `make restore-test` | Backup → destroy → restore → identical state (plaintext and encrypted) |
| `make guard-test` | Destructive-operation guards (nothing destructive is run) |
| `make research-validate SOURCE_CACHE=…` | Evidence schema, source fidelity, chart inputs (also covered by `make test` without the cache) |

Rules:
- Add tests with every behavior change. Tests for the calculation-input boundary, immutability
  and logging live in `tests/safety/` and must not be weakened.
- Do not change acceptance criteria in `docs/validation-plan.md` to make work pass. If a criterion
  is wrong, record the proposed change in `docs/decisions.md` and ask the participant.
- Withheld tests (see validation plan) are not to be used for tuning the implementation.

## Destructive test operations

Only through `scripts/lib/disposable.sh` (D-028). Never run `docker compose down -v` against the
working project `cardio`.

## Integrity rules enforced in the database

`observations` values and provenance are immutable after insert; rejected/superseded rows are
terminal; `audit_events` is append-only; deletes are refused. Do not add migrations that relax
these without a recorded decision.

## After every implementation change

1. Update `docs/current-state.md` (what changed, test results with date, known limitations).
2. Record any non-trivial design choice in `docs/decisions.md` (next free D-number).
3. Update `docs/architecture.md` if components or data flow changed.
4. Run `make schemas` if the API contract changed.
5. Keep product/commercial notes out of this repository, never mixed with observations or
   research records.
