# Current state

This is the public copy of a personal project. The private working log (results of importing real
records, discrepancy investigations, run outputs) is kept out of this repository.

## Built

- **Verified records:** CSV and text-layer PDF import, candidate review beside source, explicit
  acceptance, superseding corrections, duplicate/correction/specimen flags, collection-event
  matching, capillary vs venous series, single calculation-input boundary.
- **Evidence notebook:** evidence schema, validator with full-text quote checks, generated chart
  inputs, entries in `research/`.
- **PREVENT:** base equations verified against the corrected supplement, AHA calculator reference
  cases and a `preventr` cross-check (`docs/prevent-versioning.md`).
- **Research partner (D-056):** domain overview, questions, versioned investigations with fixed
  literature queries, next-step protocols, locked predictions, self-reported context.
- **Live provider:** Anthropic adapter behind per-run, single-use approval with payload scoping and
  a citation/scope check (D-050 to D-055, D-059).
- **Operations:** encrypted backup and restore verification, destructive-test guards.

## Tests

`make test`: 297 passed, 1 skipped. `make e2e`: 10 passed (Playwright, isolated stack, labelled fake provider).

## Known limitations

- No user authentication; loopback only (D-004).
- Image-only PDFs are not parsed; they are reported with a manual-entry path.
- Vendor layout compatibility is not claimed (see `docs/validation-plan.md`).
- Personal applicability of research entries is not assessed by the software.
