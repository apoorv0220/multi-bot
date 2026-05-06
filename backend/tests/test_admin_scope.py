from fastapi.testclient import TestClient

import main as legacy_main
from app import app
from services import usage_service


class DummySession:
    def close(self):
        return None


def override_db():
    session = DummySession()
    try:
        yield session
    finally:
        session.close()


def override_user_superadmin():
    return {"user": {"id": "u1"}, "tenant_id": None, "role": "superadmin"}


def override_user_admin():
    return {"user": {"id": "u2"}, "tenant_id": "t-admin", "role": "admin"}


def test_admin_overview_contract_for_admin(monkeypatch):
    async def fake_overview(*, user_ctx, db, tenant_id=None):
        assert user_ctx["role"] == "admin"
        return {
            "tenant_id": "t-admin",
            "total_chats": 10,
            "unique_visitors": 3,
            "embedding_token_usage": 111,
            "chat_token_usage": 222,
            "likes": 4,
            "dislikes": 1,
        }

    monkeypatch.setattr(usage_service, "overview", fake_overview)
    app.dependency_overrides[legacy_main.db_session] = override_db
    app.dependency_overrides[legacy_main.get_current_user] = override_user_admin

    client = TestClient(app)
    response = client.get("/api/admin/overview")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {
        "tenant_id",
        "total_chats",
        "unique_visitors",
        "embedding_token_usage",
        "chat_token_usage",
        "likes",
        "dislikes",
    }


def test_admin_usage_summary_contract_for_superadmin(monkeypatch):
    async def fake_usage(*, user_ctx, db, tenant_id=None):
        assert user_ctx["role"] == "superadmin"
        return {
            "tenant_id": "t-picked",
            "scope": "tenant",
            "summary": {"chat_completion": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
            "embedding_total_tokens": 33,
            "per_chat_tokens": [{"session_id": "s1", "total_tokens": 3}],
            "per_tenant_tokens": [{"tenant_id": "t-picked", "total_tokens": 33}],
        }

    monkeypatch.setattr(usage_service, "usage_summary", fake_usage)
    app.dependency_overrides[legacy_main.db_session] = override_db
    app.dependency_overrides[legacy_main.get_current_user] = override_user_superadmin

    client = TestClient(app)
    response = client.get("/api/admin/usage/summary?tenant_id=t-picked")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {
        "tenant_id",
        "scope",
        "summary",
        "embedding_total_tokens",
        "per_chat_tokens",
        "per_tenant_tokens",
    }
