from pathlib import Path

from anews_agent.config import AppConfig


def test_config_defaults_to_tavily_search_without_api_key(monkeypatch):
    monkeypatch.delenv("ANEWS_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("ANEWS_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    config = AppConfig.from_env()

    assert config.search_provider == "tavily"
    assert config.search_api_key is None
    assert config.search_base_url == "https://api.tavily.com/search"
    assert config.search_timeout_seconds == 15.0
    assert config.agent_max_tool_calls == 16
    assert config.agent_max_search_queries == 8
    assert config.agent_max_read_urls == 20


def test_config_reads_search_provider_key_and_agent_budgets(monkeypatch, tmp_path):
    monkeypatch.setenv("ANEWS_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("ANEWS_SEARCH_PROVIDER", "mock")
    monkeypatch.setenv("ANEWS_SEARCH_API_KEY", "configured-search-key")
    monkeypatch.setenv("ANEWS_SEARCH_BASE_URL", "https://search.example/api")
    monkeypatch.setenv("ANEWS_SEARCH_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("ANEWS_AGENT_MAX_TOOL_CALLS", "5")
    monkeypatch.setenv("ANEWS_AGENT_MAX_SEARCH_QUERIES", "3")
    monkeypatch.setenv("ANEWS_AGENT_MAX_READ_URLS", "7")

    config = AppConfig.from_env()

    assert config.db_path == Path(tmp_path / "agent.db")
    assert config.search_provider == "mock"
    assert config.search_api_key == "configured-search-key"
    assert config.search_base_url == "https://search.example/api"
    assert config.search_timeout_seconds == 4.5
    assert config.agent_max_tool_calls == 5
    assert config.agent_max_search_queries == 3
    assert config.agent_max_read_urls == 7


def test_config_uses_tavily_key_alias_when_generic_key_is_missing(monkeypatch):
    monkeypatch.delenv("ANEWS_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    config = AppConfig.from_env()

    assert config.search_provider == "tavily"
    assert config.search_api_key == "tvly-test"
