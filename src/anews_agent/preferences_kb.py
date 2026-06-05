from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from anews_agent.domain import PreferenceFact, PreferencePolarity, PreferenceSummary
from anews_agent.storage import NewsRepository


@dataclass(frozen=True)
class PreferenceUpdate:
    kind: str
    value: str
    polarity: PreferencePolarity = "positive"
    weight: float = 1.0
    source: str = "chat"
    evidence: str = ""


class PreferenceKnowledgeBase:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def query_preferences(self, task: str = "", limit: int = 20) -> dict[str, Any]:
        clean_task = task.strip()
        facts = (
            self.repository.search_preference_facts(clean_task, limit=limit)
            if clean_task
            else self.repository.list_preference_facts()[:limit]
        )
        legacy_preferences = self.repository.list_preferences()
        user_sources = [
            source
            for source in self.repository.list_sources()
            if source.enabled and source.user_specified
        ]
        followed_stories = self.repository.list_follows()
        summary = self.repository.latest_preference_summary()

        if summary is None:
            summary_text = self._build_summary(facts, legacy_preferences)
        else:
            summary_text = summary.summary

        return {
            "summary": summary_text,
            "facts": [
                {
                    "id": fact.id,
                    "kind": fact.kind,
                    "value": fact.value,
                    "polarity": fact.polarity,
                    "weight": fact.weight,
                    "source": fact.source,
                    "evidence": fact.evidence,
                }
                for fact in facts
            ],
            "legacy_preferences": [
                {
                    "kind": preference.kind,
                    "value": preference.value,
                    "weight": preference.weight,
                    "created_from": preference.created_from,
                }
                for preference in legacy_preferences[:limit]
            ],
            "user_sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "url": source.url,
                    "source_type": source.source_type,
                }
                for source in user_sources
            ],
            "followed_stories": [
                {
                    "id": follow.id,
                    "title": follow.title,
                    "keywords": list(follow.keywords),
                    "entities": list(follow.entities),
                }
                for follow in followed_stories
            ],
            "negative_preferences": [
                {"kind": fact.kind, "value": fact.value, "weight": fact.weight}
                for fact in facts
                if fact.polarity == "negative"
            ],
        }

    def update_preferences(
        self,
        updates: list[PreferenceUpdate | dict[str, Any]],
        *,
        now: datetime | None = None,
        source_message_id: str | None = None,
    ) -> list[PreferenceFact]:
        timestamp = now or datetime.now(timezone.utc)
        stored: list[PreferenceFact] = []
        for update in updates:
            normalized = self._normalize_update(update)
            if normalized is None:
                continue
            fact = PreferenceFact.from_value(
                kind=normalized.kind,
                value=normalized.value,
                polarity=normalized.polarity,
                weight=normalized.weight,
                source=source_message_id or normalized.source,
                evidence=normalized.evidence,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self.repository.upsert_preference_fact(fact)
            stored.append(fact)
        if stored:
            self.repository.upsert_preference_summary(
                PreferenceSummary.from_summary(
                    summary=self._build_summary(self.repository.list_preference_facts(), []),
                    created_at=timestamp,
                    source="preferences_kb",
                )
            )
        return stored

    def _normalize_update(
        self, update: PreferenceUpdate | dict[str, Any]
    ) -> PreferenceUpdate | None:
        if isinstance(update, PreferenceUpdate):
            candidate = update
        else:
            candidate = PreferenceUpdate(
                kind=str(update.get("kind") or ""),
                value=str(update.get("value") or ""),
                polarity=str(update.get("polarity") or "positive"),
                weight=_safe_weight(update.get("weight")),
                source=str(update.get("source") or "chat"),
                evidence=str(update.get("evidence") or ""),
            )
        if not candidate.kind.strip() or not candidate.value.strip():
            return None
        polarity: PreferencePolarity = (
            "negative" if candidate.polarity == "negative" else "positive"
        )
        return PreferenceUpdate(
            kind=candidate.kind.strip().lower(),
            value=candidate.value.strip(),
            polarity=polarity,
            weight=candidate.weight,
            source=candidate.source.strip() or "chat",
            evidence=candidate.evidence.strip(),
        )

    def _build_summary(
        self, facts: list[PreferenceFact], legacy_preferences: list[Any]
    ) -> str:
        positives = [fact for fact in facts if fact.polarity == "positive"]
        negatives = [fact for fact in facts if fact.polarity == "negative"]
        parts: list[str] = []
        if positives:
            values = ", ".join(f"{fact.kind}:{fact.value}" for fact in positives[:8])
            parts.append(f"正向偏好: {values}")
        if negatives:
            values = ", ".join(f"{fact.kind}:{fact.value}" for fact in negatives[:8])
            parts.append(f"负向偏好: {values}")
        if legacy_preferences:
            values = ", ".join(
                f"{preference.kind}:{preference.value}" for preference in legacy_preferences[:8]
            )
            parts.append(f"历史偏好: {values}")
        return "；".join(parts) if parts else "暂无明确偏好。"


def _safe_weight(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return parsed if parsed > 0 else 1.0
