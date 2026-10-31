"""How an accepted observation was verified.

- verification_method: 'participant_review' (the participant compared it with the source) or
  'automated_check' (accepted by the automated source checks, never reviewed by a person).
  NULL while unverified. Set once, at acceptance.

Existing accepted rows were all accepted by participant review.

Revision ID: 0003
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_GUARD = """
        CREATE OR REPLACE FUNCTION observations_guard_update() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['verification_status', 'verification_note', 'verified_at',
                                      'supersedes_observation_id', 'correction_kind'{extra}])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['verification_status', 'verification_note', 'verified_at',
                                      'supersedes_observation_id', 'correction_kind'{extra}]) THEN
                RAISE EXCEPTION 'observation % provenance and values are immutable; create a correction', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.supersedes_observation_id IS NOT NULL
               AND NEW.supersedes_observation_id IS DISTINCT FROM OLD.supersedes_observation_id THEN
                RAISE EXCEPTION 'supersedes_observation_id may only be set once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.correction_kind IS NOT NULL
               AND NEW.correction_kind IS DISTINCT FROM OLD.correction_kind THEN
                RAISE EXCEPTION 'correction_kind may only be set once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;{method_rule}
            IF OLD.verification_status IN ('rejected', 'superseded')
               AND NEW.verification_status IS DISTINCT FROM OLD.verification_status THEN
                RAISE EXCEPTION 'observation % is % and cannot change status', OLD.id, OLD.verification_status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.verification_status = 'accepted'
               AND NEW.verification_status NOT IN ('accepted', 'superseded', 'rejected') THEN
                RAISE EXCEPTION 'accepted observation % may only be superseded or withdrawn', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
"""

_METHOD_RULE = """
            IF OLD.verification_method IS NOT NULL
               AND NEW.verification_method IS DISTINCT FROM OLD.verification_method THEN
                RAISE EXCEPTION 'verification_method may only be set once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;"""


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE observations ADD COLUMN verification_method text
            CHECK (verification_method IN ('participant_review', 'automated_check'));
        """
    )
    op.execute(_GUARD.format(extra=", 'verification_method'", method_rule=_METHOD_RULE))
    # Backfill through the trigger (verification_method is now an allowed, set-once column).
    op.execute("UPDATE observations SET verification_method = 'participant_review' WHERE verified_at IS NOT NULL")


def downgrade() -> None:
    op.execute(_GUARD.format(extra="", method_rule=""))
    op.execute("ALTER TABLE observations DROP COLUMN verification_method")
