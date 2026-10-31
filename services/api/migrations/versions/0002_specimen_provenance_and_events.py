"""Specimen provenance and collection-event context.

- specimen_source: where the specimen text came from (row-level vs inherited report header).
- inherited_metadata: verbatim report-header text for every field a row inherited.
- accession_id: source identifier for the collection event, when the source states one.

Existing rows get specimen_source 'not_recorded' (their provenance was not captured).
Adding columns with defaults does not fire the observations update trigger.

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE observations
            ADD COLUMN specimen_source text NOT NULL DEFAULT 'not_recorded'
                CHECK (specimen_source IN ('row', 'report_header', 'participant_entered', 'none', 'not_recorded')),
            ADD COLUMN inherited_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN accession_id text;
        CREATE INDEX ix_observations_accession ON observations (participant_id, accession_id)
            WHERE accession_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX ix_observations_accession;
        ALTER TABLE observations DROP COLUMN accession_id, DROP COLUMN inherited_metadata,
            DROP COLUMN specimen_source;
        """
    )
