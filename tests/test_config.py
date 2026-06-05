from pathlib import Path

from anews_agent.config import AppConfig, load_env_file


def test_config_defaults_to_tavily_search_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANEWS_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("ANEWS_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    config = AppConfig.from_env(env_file=tmp_path / "missing.env")

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

    config = AppConfig.from_env(env_file=tmp_path / "missing.env")

    assert config.db_path == Path(tmp_path / "agent.db")
    assert config.search_provider == "mock"
    assert config.search_api_key == "configured-search-key"
    assert config.search_base_url == "https://search.example/api"
    assert config.search_timeout_seconds == 4.5
    assert config.agent_max_tool_calls == 5
    assert config.agent_max_search_queries == 3
    assert config.agent_max_read_urls == 7


def test_config_uses_tavily_key_alias_when_generic_key_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("ANEWS_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    config = AppConfig.from_env(env_file=tmp_path / "missing.env")

    assert config.search_provider == "tavily"
    assert config.search_api_key == "tvly-test"


def test_config_loads_local_env_file_and_supports_openai_aliases(monkeypatch, tmp_path):
    for name in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "TAVILY_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".anews.env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=deepseek-from-file",
                "OPENAI_MODEL=deepseek-file-model",
                "OPENAI_BASE_URL=https://deepseek.example",
                "ANEWS_SEARCH_PROVIDER=tavily",
                "TAVILY_API_KEY=tvly-from-file",
                "ANEWS_AGENT_MAX_TOOL_CALLS=9",
            ]
        ),
        encoding="utf-8",
    )

    config = AppConfig.from_env(env_file=env_file)

    assert config.deepseek_api_key == "deepseek-from-file"
    assert config.deepseek_model == "deepseek-file-model"
    assert config.deepseek_base_url == "https://deepseek.example"
    assert config.search_api_key == "tvly-from-file"
    assert config.agent_max_tool_calls == 9


def test_environment_variables_override_local_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".anews.env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=file-key\nTAVILY_API_KEY=file-tavily\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("ANEWS_SEARCH_API_KEY", "env-search-key")

    config = AppConfig.from_env(env_file=env_file)

    assert config.deepseek_api_key == "env-key"
    assert config.search_api_key == "env-search-key"


def test_load_env_file_ignores_comments_and_strips_quotes(tmp_path):
    env_file = tmp_path / ".anews.env"
    env_file.write_text(
        "# comment\nexport DEEPSEEK_API_KEY='quoted-key'\nEMPTY=\nBAD_LINE\n",
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values["DEEPSEEK_API_KEY"] == "quoted-key"
    assert values["EMPTY"] == ""
    assert "BAD_LINE" not in values
