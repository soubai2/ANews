from fastapi.testclient import TestClient

from anews_agent.api.app import create_app
from anews_agent.config import AppConfig


def make_client(tmp_path, *, api_key=None):
    app = create_app(
        AppConfig(
            db_path=tmp_path / "anews.db",
            deepseek_api_key=api_key,
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-flash",
        )
    )
    return TestClient(app)


def test_health_push_run_focus_follow_sources_preferences_and_ai_status(tmp_path):
    app = create_app(
        AppConfig(
            db_path=tmp_path / "anews.db",
            deepseek_api_key=None,
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-flash",
        )
    )
    client = TestClient(app)

    assert client.get("/api/health").json()["status"] == "ok"

    source_response = client.post(
        "/api/sources",
        json={"name": "Mock Tech", "url": "mock://tech", "source_type": "mock"},
    )
    assert source_response.status_code == 200

    run_response = client.post("/api/push/run")
    assert run_response.status_code == 200
    latest = run_response.json()["latest"]
    assert latest

    news_id = latest[0]["id"]
    assert client.post(f"/api/news/{news_id}/focus").status_code == 200
    assert client.post(f"/api/news/{news_id}/follow").status_code == 200
    assert client.get("/api/preferences").json()
    assert client.get("/api/follows").json()
    assert client.get("/api/ai/status").json()["provider"] == "deepseek"


def test_get_missing_news_returns_404(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/news/missing-news")

    assert response.status_code == 404


def test_patch_source_enabled_updates_listed_source(tmp_path):
    client = make_client(tmp_path)
    source = client.post(
        "/api/sources",
        json={"name": "Toggle Source", "url": "mock://toggle", "source_type": "mock"},
    ).json()

    response = client.patch(f"/api/sources/{source['id']}", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    sources = client.get("/api/sources").json()
    stored = next(item for item in sources if item["id"] == source["id"])
    assert stored["enabled"] is False


def test_delete_preference_removes_preference(tmp_path):
    client = make_client(tmp_path)
    run_response = client.post("/api/push/run")
    news_id = run_response.json()["latest"][0]["id"]
    client.post(f"/api/news/{news_id}/focus")
    preference_id = client.get("/api/preferences").json()[0]["id"]

    response = client.delete(f"/api/preferences/{preference_id}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    remaining_ids = {item["id"] for item in client.get("/api/preferences").json()}
    assert preference_id not in remaining_ids


def test_patch_ai_settings_updates_fields_without_plaintext_api_key(tmp_path):
    client = make_client(tmp_path, api_key="configured-key")

    response = client.patch(
        "/api/ai/settings",
        json={
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://api.deepseek.example",
            "fallback_enabled": False,
        },
    )

    assert response.status_code == 200
    settings = response.json()
    assert settings["provider"] == "deepseek"
    assert settings["model"] == "deepseek-reasoner"
    assert settings["base_url"] == "https://api.deepseek.example"
    assert settings["fallback_enabled"] is False
    assert settings["api_key_configured"] is True
    assert "api_key" not in settings
    assert "configured-key" not in response.text


def test_push_run_with_failing_source_records_failure_and_returns_bundle(tmp_path):
    client = make_client(tmp_path)
    source = client.post(
        "/api/sources",
        json={"name": "Failing News", "url": "https://example.invalid/news"},
    ).json()

    response = client.post("/api/push/run")

    assert response.status_code == 200
    bundle = response.json()
    assert set(bundle) == {"latest", "relevant", "follow_updates", "last_push_at", "next_push_at"}
    stored = next(item for item in client.get("/api/sources").json() if item["id"] == source["id"])
    assert stored["last_failure_at"] is not None
    assert stored["failure_reason"]
