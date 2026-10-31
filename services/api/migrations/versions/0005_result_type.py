"""Observation result type: quantity, dimensionless, categorical, bounded or text.

Existing rows default to 'quantity'; re-extraction recomputes the type from the source.

Revision ID: 0005
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE observations ADD COLUMN result_type text NOT NULL DEFAULT 'quantity'
            CHECK (result_type IN ('quantity', 'dimensionless', 'categorical', 'bounded', 'text'));
        -- Acceptance requirements now depend on the result type; free text is never accepted.
        ALTER TABLE observations DROP CONSTRAINT accepted_requires_date_and_value;
        ALTER TABLE observations ADD CONSTRAINT accepted_requires_date_and_value
            CHECK (verification_status <> 'accepted' OR (collection_date IS NOT NULL AND (
                (result_type IN ('quantity', 'bounded') AND value_numeric IS NOT NULL AND normalized_unit IS NOT NULL)
                OR (result_type = 'dimensionless' AND value_numeric IS NOT NULL)
                OR (result_type = 'categorical' AND original_value IS NOT NULL))));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE observations DROP CONSTRAINT accepted_requires_date_and_value;
        ALTER TABLE observations ADD CONSTRAINT accepted_requires_date_and_value
            CHECK (verification_status <> 'accepted'
                   OR (collection_date IS NOT NULL AND value_numeric IS NOT NULL AND normalized_unit IS NOT NULL));
        ALTER TABLE observations DROP COLUMN result_type;
    """)
