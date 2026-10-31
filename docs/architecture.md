# Architecture (Milestones 1–2)

## Components

```
Browser ──> web (Next.js, 127.0.0.1:3000) ──/api/*──> api (FastAPI, 127.0.0.1:8000) ──> db (PostgreSQL 16, not published)
                                                          └──> document store (LocalFileStorage, Docker volume)

Browser ──> notebook (Next.js, 127.0.0.1:3100)   static pages generated from research/ at build time
                                                 (no API proxy, no database, no private documents)

research/ (JSON + CSV) <── packages/evidence-tools (schema, validator, chart-input generator)
```

| Layer | Implementation | Notes |
|---|---|---|
| Interface | `apps/web`, Next.js 16 App Router, TypeScript, client components | Same-origin proxy via `next.config.ts` rewrites (D-018). No chat interface. |
| Application API | `services/api`, FastAPI, Pydantic v2 schemas | Contract exported to `packages/schemas/openapi.json`. |
| Persistent data | PostgreSQL 16, SQLAlchemy 2, Alembic | Integrity triggers in migration `0001` (D-008). |
| Original documents | `app/storage.py` `DocumentStorage` protocol, `LocalFileStorage` | Swap for private object storage later without touching callers. |
| Research execution | not built | `services/worker` placeholder (D-002). |
| Statistical modeling / risk | not built | `packages/risk-models`, `packages/response-models` placeholders. |
| Language model access | not built | No external AI calls in M1–2. |

The separation the brief asks for is preserved: interface, application logic, and (future)
research/modeling packages are separate deployable or importable units. Future calculations
read observations only through `app/calc_inputs.py`.

## Verified-record workflow

```
Import ──> extract ──> validate ──> human verification ──> accepted observations
  │           │            │               │
  │           │            │               ├─ accept   (explicit confirmation; no blocking issues; no open flags)
  │           │            │               ├─ correct  (new row supersedes old; audit before/after)
  │           │            │               └─ reject / withdraw (reason required; terminal)
  │           │            └─ extraction_issues: blocking vs warning (app/vocab.py)
  │           └─ csv_parser / pdf_parser -> RawResult (text exactly as found + source_location)
  └─ SourceDocument: original bytes, sha256, parse status/message, declared date order / collection method
```

All entry paths (CSV, PDF, manual entry, correction) go through `ingestion/candidate.py:build_candidate`,
so the same validation rules apply everywhere.

### Key modules (`services/api/app`)

| Module | Responsibility |
|---|---|
| `ingestion/dates.py` | Date parsing that never guesses month/day order or century. |
| `ingestion/normalize.py` | Test-name dictionary, unit canonical spelling (no conversion), value/range/specimen parsing. |
| `ingestion/csv_parser.py` | One-result-per-row CSV with synonym-matched headers. |
| `ingestion/pdf_parser.py` | Text-layer PDF: column positions from header words; report-level `Label: value` metadata; page rendering for review. |
| `ingestion/candidate.py` | Raw text → candidate fields + extraction issues. |
| `services/records.py` | Import, create, duplicate detection, accept/reject/correct, flag resolution, audit. |
| `services/series.py` | Longitudinal series split by collection method, unit and value origin, with comparability notices. |
| `calc_inputs.py` | The only boundary for future calculations. |
| `research/live_run.py` | One approved live run of the ApoB/LDL-P investigation: readiness gates, scrubbed payload from a snapshot of confirmed observations, per-run approval (`research_live_runs`, migration 0006), single call in a worker thread, citation and scope check. |
| `research/providers.py` | `MockProvider` for snapshots; `LiveProvider` adapter protocol with `AnthropicProvider` (key from the read-only file mount `/run/cardio-secrets`). |
| `security.py` | Local request guard (host allowlist, client header, origin check). |
| `logging_safe.py` | Error handling and logging that never records values or messages. |

### Data model

- `participants` — one seeded row (`participant-1`); every record carries `participant_id`.
- `source_documents` — original file metadata, hash, parser name/version, parse status and
  message, declarations made at upload, `duplicate_of_document_id`.
- `observations` — the brief's Observation record, with original and normalized values kept
  side by side, `extraction_status` and `verification_status` as separate columns, and
  `supersedes_observation_id` / `correction_kind` linking versions.
- `review_flags` — duplicate document, possible duplicate, conflicting value, possible lab correction.
- `audit_events` — append-only.

## Research layer and notebook (added 2026-10-21)

| Path | Responsibility |
|---|---|
| `research/evidence/*.json` | Evidence records: citation (DOI, PMID, PMCID), access (full text or abstract), study design, claims with verbatim quotes and locations, limitations, applicability constraints, source discrepancies, separate interpretation, review and publication status. |
| `research/questions/*.json` | Research questions: motivation, project connection, required personal observations, what observations would change, uncertainties, what cannot be concluded, personal applicability (`not_assessed`). |
| `research/charts/*.json` + `*.csv` | Chart specs (row → claim mapping, captions, reading notes) and generated chart inputs with source location per row. |
| `research/build-notes/*.json` | Software build entries, kept separate from scientific evidence. |
| `packages/evidence-tools` | Pydantic schema, validator (`python -m evidence_tools.validate`), CSV generator (`python -m evidence_tools.charts`). Importable by the API for Milestone 3. |
| `apps/notebook` | Renders entries, charts (SVG from CSV), source tables and build log. Build fails if a chart row differs from its claim or a question claims personal applicability. |

## Research partner (added 2026-10-27, D-056 to D-061)

Inside the existing web app and API; no new service.

| Page | API | What it does |
|---|---|---|
| `/` | `GET /research/overview` | Cardiovascular overview by domain (lipids, Lp(a), blood pressure, glucose/body, kidney, inflammation, family history, age/sex/smoking/medications). Each row carries a status: confirmed, software_checked, awaiting_review, blocked. Unknown domains are shown as unknown. Interpretations (ApoB run statements with flags, investigation summaries) are kept apart from observations. |
| `/context` | `GET/POST /context` | Self-reported context, append-only with supersession (`participant_context`). |
| `/ask` | `POST /research/questions`, `GET /research/conversations/{id}`, `/research/notes` | A question selects domains (`partner.select_domains`), retrieves usable observations and current context, and prepares a `conversation` live run. Kept notes carry across sessions. |
| `/research` | `GET /research/priorities`, `POST /research/investigations`, `GET /research/investigations/{id}` | Up to three priorities; an investigation runs the fixed literature search (`retrieval.search_literature`), then prepares an `investigation` live run. Each succeeded run is a version; `new_information` compares the latest version's retrieval with the current record. |
| `/next` | `GET /research/next`, `/research/predictions/*` | Next step (history, collectable observations, clinical-review questions) and the drafted protocol; preserve -> lock -> append results (`research_predictions`, `research_prediction_results`). |

All model calls go through `live_run.approve` / `live_run.execute` (D-050); `partner.citation_check` checks
conversation and investigation outputs. Data flow for a request: record rows + context (DB) -> retrieval ->
payload with local refs (O/C/N/P, ledger IDs, pmid:) and relative timing -> scrub check -> approval screen ->
one call -> output, citation check and refs resolved back to local records on the private page only.
Migration 0007 adds the tables and the `kind`/`context` columns of `research_live_runs`.

### Future milestones attach here

- Milestone 3 risk models consume `calc_inputs.calculation_input_observations` only.
- A job queue (`services/worker`) becomes necessary when extraction or research jobs are slow,
  retried or LLM-assisted; jobs must write candidates, never accepted observations.
