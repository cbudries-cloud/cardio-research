import uuid

from app.config import get_settings
from app.storage import LocalFileStorage

# Single local participant (decision D-004). Seeded by migration 0001.
DEFAULT_PARTICIPANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_participant_id() -> uuid.UUID:
    return DEFAULT_PARTICIPANT_ID


def get_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().document_root)
