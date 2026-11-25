from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.models import (
    AnswerTier,
    Evidence,
    QaAnswers,
    QaCard,
    Status,
)


def preferred_evidence(card: QaCard) -> list[Evidence]:
    """带 bbox/span 的证据排前面，前端默认用第一条定位与高亮。"""
    return sorted(
        card.evidence,
        key=lambda item: (item.bbox_px is None, item.span_id is None),
    )


@dataclass(frozen=True, slots=True)
class QaMatch:
    card: QaCard
    answer: str
    tier: AnswerTier


def load_qa_cards(package_root: Path) -> list[QaCard]:
    path = package_root / "derived" / "knowledge" / "cards.jsonl"
    if not path.is_file():
        return []

    cards: list[QaCard] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            card = QaCard.model_validate_json(line)
        except Exception as exc:
            raise ValueError(
                f"invalid QA card at {path.name}:{line_number}: {exc}"
            ) from exc
        if card.status is Status.active:
            cards.append(card)
    return cards


def find_qa_card(
    cards: list[QaCard],
    question: str,
    language: str | None,
) -> QaMatch | None:
    normalized_question = _normalize(question)
    if not normalized_question:
        return None

    best: tuple[int, QaCard] | None = None

    for card in sorted(cards, key=lambda item: item.priority):
        candidates = [card.question_canonical, *card.variants]
        score = 0

        for candidate in candidates:
            normalized_candidate = _normalize(candidate)
            if normalized_question == normalized_candidate:
                score = max(score, 3)
            elif (
                len(normalized_candidate) >= 3
                and (
                    normalized_candidate in normalized_question
                    or normalized_question in normalized_candidate
                )
            ):
                score = max(score, 2)

        if score and (best is None or score > best[0]):
            best = (score, card)

    if best is None:
        return None

    score, card = best
    answers = _select_answers(card, language)
    if answers is None:
        return None

    return QaMatch(
        card=card,
        answer=answers.strong if score == 3 else answers.weak,
        tier=AnswerTier.strong if score == 3 else AnswerTier.weak,
    )


def _select_answers(
    card: QaCard,
    language: str | None,
) -> QaAnswers | None:
    keys: list[str] = []
    if language:
        keys.append(language)
        if language.lower().startswith("zh"):
            keys.append("zh")
        if language.lower().startswith("en"):
            keys.append("en")

    keys.extend(card.answers)
    for key in keys:
        if key in card.answers:
            return card.answers[key]
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).lower()