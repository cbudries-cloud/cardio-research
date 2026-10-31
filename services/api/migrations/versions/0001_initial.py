"""Initial schema: participants, source documents, observations, review flags, audit events.

Integrity rules enforced in the database (not only in application code):
- observations: provenance and value columns are immutable after insert. Corrections
  create a new row that supersedes the old one.
- observations: rejected and superseded rows are terminal.
- observations, source_documents, audit_events: DELETE is refused.
- audit_events: UPDATE is refused (append-only).

Revision ID: 0001
"""

from alembic import op

from app import vocab

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DEFAULT_PARTICIPANT_ID = "00000000-0000-0000-0000-000000000001"


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE participants (
            id uuid PRIMARY KEY,
            label text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        INSERT INTO participants (id, label) VALUES ('{DEFAULT_PARTICIPANT_ID}', 'participant-1');

        CREATE TABLE source_documents (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            original_filename text NOT NULL,
            content_type text,
            size_bytes bigint NOT NULL,
            sha256 text NOT NULL,
            storage_key text NOT NULL UNIQUE,
            uploaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            document_format text NOT NULL CHECK (document_format IN {_in(vocab.DOCUMENT_FORMATS)}),
            parse_status text NOT NULL CHECK (parse_status IN {_in(vocab.PARSE_STATUSES)}),
            parse_message text,
            parser_name text,
            parser_version text,
            page_count integer,
            declared_date_order text CHECK (declared_date_order IN {_in(vocab.DATE_ORDERS)}),
            declared_collection_method text
                CHECK (declared_collection_method IN {_in(vocab.COLLECTION_METHODS)}),
            duplicate_of_document_id uuid REFERENCES source_documents(id)
        );
        CREATE INDEX ix_source_documents_sha256 ON source_documents (participant_id, sha256);

        CREATE TABLE observations (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            source_document_id uuid REFERENCES source_documents(id),
            source_location jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            entry_method text NOT NULL CHECK (entry_method IN {_in(vocab.ENTRY_METHODS)}),

            original_test_name text NOT NULL,
            normalized_test_name text,
            original_value text,
            original_unit text,
            value_comparator text CHECK (value_comparator IN ('<', '>', '<=', '>=')),
            value_numeric numeric,
            normalized_value numeric,
            normalized_unit text,
            value_origin text NOT NULL CHECK (value_origin IN {_in(vocab.VALUE_ORIGINS)}),

            collection_date date,
            collection_date_raw text,
            collection_date_status text NOT NULL
                CHECK (collection_date_status IN {_in(vocab.DATE_STATUSES)}),
            collection_date_interpretation text,
            report_date date,
            report_date_raw text,
            report_date_status text NOT NULL CHECK (report_date_status IN {_in(vocab.DATE_STATUSES)}),

            specimen_type_raw text,
            specimen_type text NOT NULL CHECK (specimen_type IN {_in(vocab.SPECIMEN_TYPES)}),
            collection_method text NOT NULL
                CHECK (collection_method IN {_in(vocab.COLLECTION_METHODS)}),
            collection_method_basis text NOT NULL
                CHECK (collection_method_basis IN {_in(vocab.COLLECTION_METHOD_BASES)}),

            laboratory text,
            method text,
            reference_range_raw text,
            reference_range_low numeric,
            reference_range_high numeric,
            lab_flag_raw text,
            collection_conditions text,
            result_status_raw text,
            reported_as_corrected boolean NOT NULL DEFAULT false,

            extraction_status text NOT NULL
                CHECK (extraction_status IN {_in(vocab.EXTRACTION_STATUSES)}),
            extraction_issues jsonb NOT NULL DEFAULT '[]'::jsonb,

            verification_status text NOT NULL DEFAULT 'unverified'
                CHECK (verification_status IN {_in(vocab.VERIFICATION_STATUSES)}),
            verification_note text,
            verified_at timestamptz,

            supersedes_observation_id uuid REFERENCES observations(id),
            correction_kind text CHECK (correction_kind IN {_in(vocab.CORRECTION_KINDS)}),
            correction_reason text,

            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_by text NOT NULL,

            CONSTRAINT accepted_requires_timestamp
                CHECK (verification_status <> 'accepted' OR verified_at IS NOT NULL),
            CONSTRAINT accepted_requires_date_and_value
                CHECK (verification_status <> 'accepted'
                       OR (collection_date IS NOT NULL AND value_numeric IS NOT NULL
                           AND normalized_unit IS NOT NULL))
        );
        CREATE INDEX ix_observations_participant_status
            ON observations (participant_id, verification_status);
        CREATE INDEX ix_observations_test_date
            ON observations (participant_id, normalized_test_name, collection_date);
        CREATE INDEX ix_observations_document ON observations (source_document_id);
        CREATE UNIQUE INDEX ux_observations_single_successor
            ON observations (supersedes_observation_id) WHERE supersedes_observation_id IS NOT NULL;

        CREATE TABLE review_flags (
            id uuid PRIMARY KEY,
            participant_id uuid NOT NULL REFERENCES participants(id),
            kind text NOT NULL CHECK (kind IN {_in(vocab.FLAG_KINDS)}),
            observation_id uuid REFERENCES observations(id),
            related_observation_id uuid REFERENCES observations(id),
            document_id uuid REFERENCES source_documents(id),
            related_document_id uuid REFERENCES source_documents(id),
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
            resolution text CHECK (resolution IN {_in(vocab.FLAG_RESOLUTIONS)}),
            resolution_note text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            resolved_at timestamptz,
            CONSTRAINT resolved_has_resolution
                CHECK (status = 'open' OR (resolution IS NOT NULL AND resolved_at IS NOT NULL))
        );
        CREATE INDEX ix_review_flags_open ON review_flags (participant_id, status);
        CREATE INDEX ix_review_flags_obs ON review_flags (observation_id);
        CREATE INDEX ix_review_flags_related_obs ON review_flags (related_observation_id);

        CREATE TABLE audit_events (
            id bigserial PRIMARY KEY,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            participant_id uuid REFERENCES participants(id),
            actor text NOT NULL,
            action text NOT NULL,
            entity_type text NOT NULL,
            entity_id uuid NOT NULL,
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb
        );
        CREATE INDEX ix_audit_events_entity ON audit_events (entity_id);

        -- Integrity triggers ------------------------------------------------------

        CREATE FUNCTION refuse_modification() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not permitted', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION refuse_modification();
        CREATE TRIGGER observations_no_delete
            BEFORE DELETE ON observations
            FOR EACH ROW EXECUTE FUNCTION refuse_modification();
        CREATE TRIGGER source_documents_no_delete
            BEFORE DELETE ON source_documents
            FOR EACH ROW EXECUTE FUNCTION refuse_modification();

        CREATE FUNCTION observations_guard_update() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['verification_status', 'verification_note', 'verified_at',
                                      'supersedes_observation_id', 'correction_kind'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['verification_status', 'verification_note', 'verified_at',
                                      'supersedes_observation_id', 'correction_kind']) THEN
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
            END IF;
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

        CREATE TRIGGER observations_guard_update
            BEFORE UPDATE ON observations
            FOR EACH ROW EXECUTE FUNCTION observations_guard_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE audit_events;
        DROP TABLE review_flags;
        DROP TABLE observations;
        DROP TABLE source_documents;
        DROP TABLE participants;
        DROP FUNCTION observations_guard_update();
        DROP FUNCTION refuse_modification();
        """
    )
