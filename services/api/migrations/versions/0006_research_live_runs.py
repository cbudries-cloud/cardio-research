"""Live research runs with per-run participant approval.

One row per proposed live model call. The exact outgoing request, its hash, the provider, model,
endpoint and snapshot are fixed at insert. Status moves forward only:
  awaiting_approval -> running (approval recorded) -> succeeded | failed
  awaiting_approval -> withdrawn
Terminal rows cannot change; rows cannot be deleted.

Revision ID: 0006
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_live_runs (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            snapshot_id uuid NOT NULL REFERENCES research_snapshots(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            status text NOT NULL CHECK (status IN ('awaiting_approval', 'running', 'succeeded', 'failed', 'withdrawn')),
            provider text NOT NULL,
            model text NOT NULL,
            endpoint text NOT NULL,
            request_body jsonb NOT NULL,
            payload_sha256 text NOT NULL,
            local_refs jsonb NOT NULL,
            evidence_ids jsonb NOT NULL,
            estimate jsonb NOT NULL,
            limits jsonb NOT NULL,
            data_handling jsonb NOT NULL,
            approval jsonb,
            approved_at timestamptz,
            completed_at timestamptz,
            response_id text,
            response_model text,
            stop_reason text,
            usage jsonb,
            cost_usd numeric,
            latency_ms double precision,
            output jsonb,
            citation_check jsonb,
            comparison jsonb,
            error text
        );
        CREATE FUNCTION research_live_runs_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE on research_live_runs is not permitted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status IN ('succeeded', 'failed', 'withdrawn') THEN
                RAISE EXCEPTION 'research live run % is final', OLD.id USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (NEW.participant_id, NEW.snapshot_id, NEW.created_at, NEW.provider, NEW.model, NEW.endpoint,
                NEW.request_body, NEW.payload_sha256, NEW.local_refs, NEW.evidence_ids, NEW.estimate, NEW.limits,
                NEW.data_handling)
               IS DISTINCT FROM
               (OLD.participant_id, OLD.snapshot_id, OLD.created_at, OLD.provider, OLD.model, OLD.endpoint,
                OLD.request_body, OLD.payload_sha256, OLD.local_refs, OLD.evidence_ids, OLD.estimate, OLD.limits,
                OLD.data_handling) THEN
                RAISE EXCEPTION 'the proposed request of a live run cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT ((OLD.status = 'awaiting_approval' AND NEW.status IN ('running', 'withdrawn'))
                    OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed'))) THEN
                RAISE EXCEPTION 'live run status % -> % is not permitted', OLD.status, NEW.status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.status = 'running' AND (NEW.approval IS NULL OR NEW.approved_at IS NULL) THEN
                RAISE EXCEPTION 'a live run cannot start without a recorded approval' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.approval IS NOT NULL AND NEW.approval IS DISTINCT FROM OLD.approval THEN
                RAISE EXCEPTION 'a recorded approval cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_live_runs_guard
            BEFORE UPDATE OR DELETE ON research_live_runs
            FOR EACH ROW EXECUTE FUNCTION research_live_runs_guard();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE research_live_runs")
    op.execute("DROP FUNCTION research_live_runs_guard()")
