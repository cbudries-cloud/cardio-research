"""Local-only request guard. Not authentication; see docs/safety-boundaries.md."""

from conftest import fixture_bytes


def _upload(c, **headers):
    return c.post("/api/v1/documents", headers=headers,
                  files={"file": ("a.csv", fixture_bytes("synthetic_venous_panel_2022.csv"), "text/csv")})


def test_state_change_without_client_header_is_refused(raw_client):
    assert _upload(raw_client).status_code == 403
    assert raw_client.get("/api/v1/documents").json() == []


def test_foreign_origin_is_refused(raw_client):
    r = _upload(raw_client, **{"X-Cardio-Client": "web", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_allowed_origin_is_accepted(raw_client):
    r = _upload(raw_client, **{"X-Cardio-Client": "web", "Origin": "http://127.0.0.1:3000"})
    assert r.status_code == 201


def test_unexpected_host_header_is_refused(raw_client):
    assert raw_client.get("/api/v1/health", headers={"Host": "attacker.example"}).status_code == 400


def test_no_cors_grant(raw_client):
    r = raw_client.options("/api/v1/documents", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
