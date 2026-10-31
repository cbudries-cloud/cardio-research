"""Historical results, participant confirmation of automated acceptances, research snapshots.

- observations.reported_as: 'current' (the report's own result) or 'historical_in_later_report'
  (a previous result reprinted by a later report, e.g. a "Previous Result and Date" column).
- verification_method may change exactly once more, from 'automated_check' to
  'participant_review', when the participant confirms the value against its source.
- research_snapshots: append-only, versioned inputs and outputs of the research runtime.

Revision ID: 0004
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_OLD_RULE = """IF OLD.verification_method IS NOT NULL
               AND NEW.verification_method IS DISTINCT FROM OLD.verification_method THEN"""
_NEW_RULE = """IF OLD.verification_method IS NOT NULL
               AND NEW.verification_method IS DISTINCT FROM OLD.verification_method
               AND NOT (OLD.verification_method = 'automated_check'
                        AND NEW.verification_method = 'participant_review'
                        AND NEW.verification_status = 'accepted') THEN"""


def _swap(old: str, new: str) -> None:
    op.execute(f"""
        DO $do$
        DECLARE src text;
        BEGIN
            SELECT pg_get_functiondef('observations_guard_update'::regproc) INTO src;
            IF position({_q(old)} in src) = 0 THEN
                RAISE EXCEPTION 'guard function does not contain the expected rule';
            END IF;
            EXECUTE replace(src, {_q(old)}, {_q(new)});
        END
        $do$;
    """)


def _q(s: str) -> str:
    return "$q$" + s + "$q$"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE observations ADD COLUMN reported_as text NOT NULL DEFAULT 'current'
            CHECK (reported_as IN ('current', 'historical_in_later_report'));
    """)
    _swap(_OLD_RULE, _NEW_RULE)
    op.execute("""
        CREATE TABLE research_snapshots (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            version integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            runtime_version text NOT NULL,
            rules_sha256 text NOT NULL,
            inputs jsonb NOT NULL,
            outputs jsonb NOT NULL,
            UNIQUE (participant_id, version)
        );
        CREATE TRIGGER research_snapshots_append_only
            BEFORE UPDATE OR DELETE ON research_snapshots
            FOR EACH ROW EXECUTE FUNCTION refuse_modification();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE research_snapshots")
    _swap(_NEW_RULE, _OLD_RULE)
    op.execute("ALTER TABLE observations DROP COLUMN reported_as")
