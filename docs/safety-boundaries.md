# Safety boundaries

## What the application may and may not do (research partner, D-056)

The application organizes and verifies records, answers questions about them, investigates
research questions the participant selects, discusses measurement options and drafts
prospective protocols. It does **not** prescribe or adjust medication or supplements, order
tests, diagnose, state a numerical personal risk, interpret laboratory flags as findings, or
start an experiment. There is no physician in the loop; testing and treatment questions are
listed for clinical review, and nothing in this build directs a medical action.

Laboratory reference ranges and flags are stored verbatim and shown as "laboratory flag, not a
diagnosis". Clinical decision thresholds are not stored in this milestone; when they are, they
must be stored separately from reference ranges.

## Data integrity boundaries

- Extraction creates candidates only. An observation becomes usable for calculations only after
  explicit acceptance, and only while it is not involved in an open review flag
  (`services/api/app/calc_inputs.py`).
- Blocking extraction issues (missing value, non-numeric value, missing unit, missing/ambiguous/
  unparseable collection date) prevent acceptance until corrected.
- Corrections never overwrite. The database refuses in-place edits of values and provenance,
  deletion of observations/documents, and any change to audit events.
- Unknown stays unknown: ambiguous dates are not guessed; unknown specimens and collection
  methods are labeled unknown; no units are converted; capillary and venous results form
  separate series.

## Local-only operation (deliberate revision to Milestone 1)

The brief lists authentication in Milestone 1. For this initial local-only build, user-account
authentication is **deferred** (decision D-004). In its place:

- Every published port binds to `127.0.0.1` (`docker-compose.yml`). The database is not published.
- The API rejects requests whose `Host` header is not allowlisted (DNS-rebinding defense).
- State-changing requests must carry `X-Cardio-Client: web` and, if an `Origin` header is
  present, an allowlisted origin. No CORS grants are issued.
- The browser uses one origin: Next.js proxies `/api/*` to the API.

**This is not authentication.** Any process running as a local user on the host can call the
API. Before any remote or LAN access, the following are prerequisites (Milestone 1 items still
open for remote use): user authentication, private document access controls, secret
management, TLS, a review of every exposed endpoint, and a tested backup restore on the target.

## Encryption

- **At rest:** the application does not encrypt the database or document store. Full-disk
  encryption on the host (FileVault on macOS) is a **host requirement**. Docker Desktop stores
  volumes inside its VM disk image on the host disk, so host encryption covers them.
- **Backups:** `scripts/backup.sh` writes outside the repository with `umask 077`. Set
  `CARDIO_BACKUP_PASSPHRASE_FILE` to encrypt backups (openssl AES-256-CBC, PBKDF2 200k).
  Without it, backups are plaintext and rely on host disk encryption.
- **In transit:** loopback HTTP only. No external network calls are made by the application.

## Sensitive-data handling in development

- Synthetic fixtures only (`fixtures/synthetic/`), clearly labeled. They represent generic
  layouts and do **not** establish compatibility with any vendor, including Function Health.
- Real records must never enter the repository, coding-agent context, logs or test output.
  `.gitignore` excludes common data/backup paths; backup scripts refuse repo-internal targets.
- Logs: API access logs contain method, path (opaque UUIDs) and status. Application errors log
  exception type and code location only, never messages (`app/logging_safe.py`). Tested in
  `tests/safety/test_no_health_data_in_logs.py`.
- Next.js telemetry is disabled. No analytics, crash reporting or third-party scripts.
- No external AI services are called. When Milestone 3+ adds a provider adapter, it must send the
  minimum necessary data and the retention controls of the exact endpoints used must be checked.

## Research notebook boundaries (added 2026-10-21)

- The notebook contains published evidence only. It is a separate app with no connection to the records API or database; the browser test confirms records API paths return 404 on it and scans pages for paths, credentials and log markers.
- Personal applicability is `not_assessed` for every question until verified personal records exist and an assessment is recorded (D-031).
- Cohort event rates and trial averages are labelled with their population and horizon and are never presented as personal risk. Model-based estimates are labelled as such.
- Nothing is published automatically. The notebook runs on loopback only; `publication.status` cannot be `published`.
- Literature retrieval uses DOIs and PMIDs only; no personal information is sent. Full texts are cached outside the repository and not redistributed.
- Interface demonstrations in the build log use synthetic fixtures and are labelled as such.

## Out of scope until a qualified reviewer exists

Medication changes, supplement regimens, genetic diagnosis, imaging decisions and any medically
consequential experiment remain outside the application's authority. The system may later
prepare questions for clinical review; it must not convert a hypothesis into an instruction.
