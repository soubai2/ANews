from datetime import datetime, timezone

from anews_agent.chat import ChatService
from anews_agent.domain import AISettings
from anews_agent.storage import NewsRepository


def test_chat_service_persists_degraded_message_without_deepseek_key(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    service = ChatService(
        repository=repo,
        settings=AISettings.default(),
        api_key=None,
        now=lambda: now,
    )
    session = service.create_session("AI 新闻")

    result = service.send_message(session.id, "今天 AI 芯片有什么新闻？")

    assert result.agent_run is not None
    assert result.agent_run.status == "failed"
    assert result.agent_run.degradation_reason == "deepseek_api_key_missing"
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert "DeepSeek 当前不可用" in result.messages[1].content
    assert repo.list_chat_messages(session.id)[1].agent_run_id == result.agent_run.id
