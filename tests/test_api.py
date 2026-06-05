from fastapi.testclient import TestClient

import anews_agent.api.app as app_module
from anews_agent.config import AppConfig


def make_client(tmp_path, *, api_key=None, raise_server_exceptions=True):
    app = app_module.create_app(
        AppConfig(
            db_path=tmp_path / "anews.db",
            deepseek_api_key=api_key,
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-flash",
        )
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_health_push_run_focus_follow_sources_preferences_and_ai_status(tmp_path):
    app = app_module.create_app(
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


def test_ai_and_search_status_make_degradation_visible(tmp_path):
    client = make_client(tmp_path)

    ai_status = client.get("/api/ai/status").json()
    search_status = client.get("/api/search/status").json()

    assert ai_status["provider"] == "deepseek"
    assert ai_status["available"] is False
    assert ai_status["degraded"] is True
    assert ai_status["degradation_reason"] == "deepseek_api_key_missing"
    assert search_status["provider"] == "tavily"
    assert search_status["configured"] is False
    assert search_status["available"] is False
    assert search_status["degraded"] is True
    assert search_status["degradation_reason"] == "search_api_key_missing"
    assert search_status["live_check"] is False


def test_get_missing_news_returns_404(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/news/missing-news")

    assert response.status_code == 404


def test_cors_allows_local_renderer_origin(tmp_path):
    client = make_client(tmp_path)

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


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


def test_push_does_not_create_default_source_when_all_sources_are_disabled(tmp_path):
    client = make_client(tmp_path)
    source = client.post(
        "/api/sources",
        json={"name": "Disabled Source", "url": "mock://disabled", "source_type": "mock"},
    ).json()
    client.patch(f"/api/sources/{source['id']}", json={"enabled": False})

    current_response = client.get("/api/push")
    run_response = client.post("/api/push/run")

    assert current_response.status_code == 200
    assert run_response.status_code == 200
    assert run_response.json()["latest"] == []
    assert run_response.json()["relevant"] == []
    assert run_response.json()["follow_updates"] == []
    sources = client.get("/api/sources").json()
    assert [item["id"] for item in sources] == [source["id"]]
    assert sources[0]["enabled"] is False


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


def test_patch_ai_settings_cannot_set_api_key_configured_without_config_key(tmp_path):
    client = make_client(tmp_path)

    response = client.patch(
        "/api/ai/settings",
        json={
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://api.deepseek.example",
            "enabled": False,
            "fallback_enabled": False,
            "api_key_configured": True,
        },
    )

    assert response.status_code == 200
    settings = response.json()
    assert settings["model"] == "deepseek-reasoner"
    assert settings["enabled"] is False
    assert settings["fallback_enabled"] is False
    assert settings["api_key_configured"] is False
    assert client.get("/api/ai/status").json()["api_key_configured"] is False


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


def test_add_source_missing_name_returns_422(tmp_path):
    client = make_client(tmp_path, raise_server_exceptions=False)

    response = client.post("/api/sources", json={"url": "mock://missing-name"})

    assert response.status_code == 422


def test_create_app_starts_scheduler_when_enabled(tmp_path, monkeypatch):
    events = []

    class SpyScheduler:
        def start(self):
            events.append("start")

        def shutdown(self, wait=False):
            events.append(("shutdown", wait))

    def fake_create_push_scheduler(push_job, *, interval_hours):
        events.append(("created", interval_hours))
        return SpyScheduler()

    monkeypatch.setattr(app_module, "create_push_scheduler", fake_create_push_scheduler)
    app = app_module.create_app(
        AppConfig(
            db_path=tmp_path / "anews.db",
            deepseek_api_key=None,
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-flash",
            push_interval_hours=2,
        ),
        enable_scheduler=True,
    )

    with TestClient(app):
        assert events == [("created", 2), "start"]

    assert events == [("created", 2), "start", ("shutdown", False)]


def test_patch_source_missing_enabled_returns_422(tmp_path):
    client = make_client(tmp_path, raise_server_exceptions=False)
    source = client.post(
        "/api/sources",
        json={"name": "Missing Enabled", "url": "mock://missing-enabled"},
    ).json()

    response = client.patch(f"/api/sources/{source['id']}", json={})

    assert response.status_code == 422
