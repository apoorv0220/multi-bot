from fastapi.testclient import TestClient

import main as legacy_main
from app import app
from services import usage_service


def override_user():
    return {"user": {"id": "u-admin"}, "tenant_id": "tenant-a", "role": "admin"}


class DummySession:
    def close(self):
        return None


def override_db():
    session = DummySession()
    try:
        yield session
    finally:
        session.close()


def test_usage_summary_returns_expected_shapes(monkeypatch):
    async def fake_usage(*, user_ctx, db, tenant_id=None):
        return {
            "tenant_id": "tenant-a",
            "scope": "tenant",
            "summary": {
                "chat_completion": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                "chat_embedding": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
                "index_embedding": {"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100},
            },
            "embedding_total_tokens": 105,
            "per_chat_tokens": [{"session_id": "s1", "total_tokens": 25}],
            "per_tenant_tokens": [{"tenant_id": "tenant-a", "total_tokens": 130}],
        }

    monkeypatch.setattr(usage_service, "usage_summary", fake_usage)
    app.dependency_overrides[legacy_main.db_session] = override_db
    app.dependency_overrides[legacy_main.get_current_user] = override_user
    client = TestClient(app)
    response = client.get("/api/admin/usage/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["embedding_total_tokens"] == 105
    assert isinstance(body["per_chat_tokens"], list)
    assert isinstance(body["per_tenant_tokens"], list)
