from fastapi.testclient import TestClient

from app import app
from services import chat_service, public_service


def test_public_visitor_profile_contract(monkeypatch):
    async def fake_profile(*, db, x_widget_key, x_visitor_id, origin, request_obj=None):
        assert x_widget_key == "k1"
        assert x_visitor_id == "v1"
        return {"profile_exists": True}

    monkeypatch.setattr(public_service, "get_visitor_profile", fake_profile)
    client = TestClient(app)
    response = client.get("/api/public/visitor-profile", headers={"X-Widget-Key": "k1", "X-Visitor-Id": "v1"})
    assert response.status_code == 200
    assert response.json() == {"profile_exists": True}


def test_public_config_exposes_max_results_default(monkeypatch):
    async def fake_get_widget_config(*, db, x_widget_key, origin, request_obj):
        assert x_widget_key == "k1"
        return {
            "brand_name": "Shop",
            "max_results_default": 20,
            "max_results_absolute_ceiling": 50,
        }

    monkeypatch.setattr(public_service, "get_widget_config", fake_get_widget_config)
    client = TestClient(app)
    response = client.get(
        "/api/public/config",
        headers={"X-Widget-Key": "k1"},
    )
    assert response.status_code == 200
    assert response.json()["max_results_default"] == 20


def test_public_chat_contract(monkeypatch):
    async def fake_chat(*, request, db, x_widget_key, x_visitor_id, origin, request_obj=None):
        assert request.message == "hello"
        return {
            "response": "Hi",
            "session_id": "s1",
            "message_id": "m1",
            "source": "vector_search",
            "confidence": 0.75,
            "sources": [],
        }

    monkeypatch.setattr(chat_service, "run_public_chat", fake_chat)
    client = TestClient(app)
    response = client.post(
        "/api/public/chat",
        json={"message": "hello", "max_results": 3},
        headers={"X-Widget-Key": "k1", "X-Visitor-Id": "v1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert {"response", "session_id", "message_id"}.issubset(data.keys())
