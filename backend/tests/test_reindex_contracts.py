from fastapi.testclient import TestClient

import main as legacy_main
from app import app
from services import reindex_service


class DummySession:
    def close(self):
        return None


def override_db():
    session = DummySession()
    try:
        yield session
    finally:
        session.close()


def override_user():
    return {"user": {"id": "u-admin"}, "tenant_id": "tenant-a", "role": "admin"}


def test_reindex_trigger_contract(monkeypatch):
    async def fake_trigger(*, request, user_ctx, db):
        assert request.tenant_id == "tenant-a"
        return {"job_id": "job-1", "status": "started"}

    monkeypatch.setattr(reindex_service, "trigger_reindex", fake_trigger)
    app.dependency_overrides[legacy_main.db_session] = override_db
    app.dependency_overrides[legacy_main.get_current_user] = override_user
    client = TestClient(app)
    response = client.post("/api/reindex", json={"tenant_id": "tenant-a"})
    assert response.status_code == 200
    assert response.json() == {"job_id": "job-1", "status": "started"}


def test_reindex_jobs_contract(monkeypatch):
    async def fake_list(*, user_ctx, db, tenant_id=None):
        assert tenant_id == "tenant-a"
        return [{"id": "job-1", "status": "completed", "tenant_id": "tenant-a"}]

    monkeypatch.setattr(reindex_service, "list_reindex_jobs", fake_list)
    app.dependency_overrides[legacy_main.db_session] = override_db
    app.dependency_overrides[legacy_main.get_current_user] = override_user
    client = TestClient(app)
    response = client.get("/api/reindex/jobs?tenant_id=tenant-a")
    assert response.status_code == 200
    assert response.json() == [{"id": "job-1", "status": "completed", "tenant_id": "tenant-a"}]
