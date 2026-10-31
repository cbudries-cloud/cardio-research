"""Research partner: self-reported context, conversations, notes, investigations, predictions.

- participant_context: self-reported health context (blood pressure, family history, smoking,
  medications, body measurements, demographics). Append-only; a correction is a new row that
  names the row it supersedes.
- research_conversations / research_messages: questions asked in the app. Append-only. The
  answer to a question is the live run prepared for it (research_live_runs.context.message_id).
- research_notes: context and working hypotheses the participant explicitly accepted. Conversation
  history alone never creates one. Status moves accepted -> withdrawn only.
- research_investigations: a research question selected by the participant. Each version is a
  live run of kind 'investigation' (immutable, approved per run).
- research_predictions: a protocol and prediction preserved before its outcome. Once locked the
  row cannot change; results are appended to research_prediction_results, only after locking.
- research_live_runs gains kind and context; both are part of the immutable proposed request.

Revision ID: 0007
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _no_change(table: str) -> str:
    return f"""
        CREATE FUNCTION {table}_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on {table} is not permitted', TG_OP USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {table}_append_only();
    """


def upgrade() -> None:
    op.execute("""
        CREATE TABLE participant_context (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            domain text NOT NULL CHECK (domain IN ('demographics', 'blood_pressure', 'family_history', 'smoking',
                                                   'medications', 'body', 'diabetes', 'other')),
            item text NOT NULL,
            value_text text NOT NULL,
            as_of date,
            note text,
            supersedes_id uuid REFERENCES participant_context(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE research_conversations (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            title text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE research_messages (
            id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES research_conversations(id),
            participant_id uuid NOT NULL REFERENCES participants(id),
            text text NOT NULL,
            retrieval jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE research_notes (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            kind text NOT NULL CHECK (kind IN ('working_hypothesis', 'open_question', 'context_note')),
            text text NOT NULL,
            status text NOT NULL CHECK (status IN ('accepted', 'withdrawn')),
            source_run_id uuid REFERENCES research_live_runs(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            withdrawn_at timestamptz
        );
        CREATE TABLE research_investigations (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            priority_id text NOT NULL,
            question text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE research_predictions (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            investigation_id uuid REFERENCES research_investigations(id),
            source_run_id uuid REFERENCES research_live_runs(id),
            protocol jsonb NOT NULL,
            status text NOT NULL CHECK (status IN ('draft', 'locked')),
            protocol_sha256 text,
            locked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE research_prediction_results (
            id uuid PRIMARY KEY,
            prediction_id uuid NOT NULL REFERENCES research_predictions(id),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            observation_ids jsonb NOT NULL,
            context_ids jsonb NOT NULL,
            result_text text NOT NULL,
            assessment text NOT NULL CHECK (assessment IN ('consistent_with_prediction', 'counts_against', 'inconclusive'))
        );

        ALTER TABLE research_live_runs
            ADD COLUMN kind text NOT NULL DEFAULT 'apob_ldlp' CHECK (kind IN ('apob_ldlp', 'conversation', 'investigation')),
            ADD COLUMN context jsonb NOT NULL DEFAULT '{}'::jsonb;
    """)
    for t in ("participant_context", "research_conversations", "research_messages", "research_investigations",
              "research_prediction_results"):
        op.execute(_no_change(t))
    op.execute("""
        CREATE FUNCTION research_notes_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE on research_notes is not permitted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT (OLD.status = 'accepted' AND NEW.status = 'withdrawn' AND NEW.withdrawn_at IS NOT NULL)
               OR (NEW.participant_id, NEW.kind, NEW.text, NEW.source_run_id, NEW.created_at)
                  IS DISTINCT FROM (OLD.participant_id, OLD.kind, OLD.text, OLD.source_run_id, OLD.created_at) THEN
                RAISE EXCEPTION 'a research note can only be withdrawn' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_notes_guard BEFORE UPDATE OR DELETE ON research_notes
            FOR EACH ROW EXECUTE FUNCTION research_notes_guard();

        CREATE FUNCTION research_predictions_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE on research_predictions is not permitted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status = 'locked' THEN
                RAISE EXCEPTION 'prediction % is locked', OLD.id USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT (NEW.status = 'locked' AND NEW.protocol_sha256 IS NOT NULL AND NEW.locked_at IS NOT NULL)
               OR (NEW.participant_id, NEW.investigation_id, NEW.source_run_id, NEW.protocol, NEW.created_at)
                  IS DISTINCT FROM (OLD.participant_id, OLD.investigation_id, OLD.source_run_id, OLD.protocol, OLD.created_at) THEN
                RAISE EXCEPTION 'a draft prediction can only be locked as it is' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_predictions_guard BEFORE UPDATE OR DELETE ON research_predictions
            FOR EACH ROW EXECUTE FUNCTION research_predictions_guard();

        CREATE FUNCTION research_prediction_results_locked() RETURNS trigger AS $$
        BEGIN
            IF (SELECT status FROM research_predictions WHERE id = NEW.prediction_id) IS DISTINCT FROM 'locked' THEN
                RAISE EXCEPTION 'results can be recorded only for a locked prediction' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_prediction_results_locked BEFORE INSERT ON research_prediction_results
            FOR EACH ROW EXECUTE FUNCTION research_prediction_results_locked();
    """)
    # kind and context join the immutable proposed request.
    op.execute("""
        CREATE OR REPLACE FUNCTION research_live_runs_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE on research_live_runs is not permitted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status IN ('succeeded', 'failed', 'withdrawn') THEN
                RAISE EXCEPTION 'research live run % is final', OLD.id USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (NEW.participant_id, NEW.snapshot_id, NEW.created_at, NEW.provider, NEW.model, NEW.endpoint,
                NEW.request_body, NEW.payload_sha256, NEW.local_refs, NEW.evidence_ids, NEW.estimate, NEW.limits,
                NEW.data_handling, NEW.kind, NEW.context)
               IS DISTINCT FROM
               (OLD.participant_id, OLD.snapshot_id, OLD.created_at, OLD.provider, OLD.model, OLD.endpoint,
                OLD.request_body, OLD.payload_sha256, OLD.local_refs, OLD.evidence_ids, OLD.estimate, OLD.limits,
                OLD.data_handling, OLD.kind, OLD.context) THEN
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
    """)


def downgrade() -> None:
    raise NotImplementedError("0007 is not reversible: it holds participant records")
