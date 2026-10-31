# services/worker (placeholder)

No job queue exists in Milestones 1–2 (decision D-002). Parsing runs synchronously in the API.

When research jobs arrive (Milestone 3+), the worker must provide explicit workflow states,
checkpoints, retry limits, cancellation, deduplication and spending limits, and must never write
accepted observations or half-written conclusions into the accepted record.
