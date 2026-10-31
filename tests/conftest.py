"""Shared fixtures. Tests run inside the api-test container against a dedicated
cardio_test database and synthetic fixtures only (see AGENTS.md)."""

import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

FIXTURES = Path(os.environ.get("CARDIO_FIXTURES", "/fixtures/synthetic"))
TEST_DB = os.environ["CARDIO_DATABASE_URL"]
ADMIN_DB = os.environ["CARDIO_ADMIN_DATABASE_URL"]
TABLES = ("research_prediction_results, research_predictions, research_notes, research_messages, "
          "research_conversations, research_investigations, participant_context, research_live_runs, research_snapshots, audit_events, review_flags, observations, source_documents")


@pytest.fixture(scope="session", autouse=True)
def database():
    assert TEST_DB.rsplit("/", 1)[-1] == "cardio_test", "tests must never run against a non-test database"
    assert os.environ["CARDIO_DOCUMENT_ROOT"].startswith("/tmp/"), "tests must never use a real document store"
    admin = create_engine(ADMIN_DB, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS cardio_test WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE cardio_test"))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("script_location", "/app/migrations")
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_state(database):
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()
    root = Path(os.environ["CARDIO_DOCUMENT_ROOT"])
    if root.exists():
        for child in root.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), headers={"X-Cardio-Client": "web"}) as c:
        yield c


@pytest.fixture
def raw_client():
    """Client without the local client header, for request-guard tests."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def upload(client, name: str, data: bytes | None = None, **form):
    content = data if data is not None else fixture_bytes(name)
    mime = "application/pdf" if name.endswith(".pdf") else "text/csv"
    r = client.post("/api/v1/documents", files={"file": (name, content, mime)}, data=form)
    assert r.status_code == 201, r.text
    return r.json()


def observations_for(client, doc_id: str) -> list[dict]:
    r = client.get(f"/api/v1/documents/{doc_id}")
    assert r.status_code == 200, r.text
    return r.json()["observations"]


def by_test(observations: list[dict], normalized: str) -> list[dict]:
    return [o for o in observations if o["normalized_test_name"] == normalized]


def accept(client, obs_id: str):
    return client.post(f"/api/v1/observations/{obs_id}/accept", json={"confirm_source_matches": True})


def calc_inputs(client, test: str | None = None) -> list[dict]:
    params = {"normalized_test_name": test} if test else {}
    r = client.get("/api/v1/calculation-inputs/observations", params=params)
    assert r.status_code == 200, r.text
    return r.json()
