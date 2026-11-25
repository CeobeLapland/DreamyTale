"""Online conductor: pick tools for one utterance, run them, record the turn.

`handle_interaction` knows how to answer a *single* intent. This module is the
online counterpart of `pipeline/orchestrator.py`:

- a tool registry (control / seek / search / highlight / click / qa / router);
- a rule fast path that classifies the utterance without a model;
- a conservative multi-intent split ("先找到……然后告诉我为什么"), where the
  second step inherits the page the first step landed on;
- one `Turn` and one `Trace` per request (contract §7 / §8.5).

It deliberately stops at the rule path: no extra LLM call just to plan. The
trace records the chosen tools, their latency, and the result, which is what
the demo's "生成链路 / 工具调用" panel shows.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.app.answer_tts import synthesize_answer
from backend.app.interaction import handle_interaction, interaction_kind_for
from backend.app.models import (
    ActionType,
    AnswerPayload,
    AnswerTier,
    ErrorInfo,
    InteractionAction,
    InteractionKind,
    InteractionRequest,
    InteractionResponse,
    LatencyBreakdown,
    Trace,
    TraceStage,
    Turn,
)
from backend.app.script_parser import classify_instruction
from backend.app.session_log import write_trace, write_turn


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    kind: InteractionKind
    description: str

    def run(
        self,
        request: InteractionRequest,
        package,
        package_root: Path | None,
    ) -> InteractionResponse:
        return handle_interaction(request, package, package_root)


TOOLS: dict[InteractionKind, Tool] = {
    InteractionKind.auto: Tool(
        "router", InteractionKind.auto, "规则意图路由：把一句话分给下面的工具"
    ),
    InteractionKind.control: Tool(
        "player", InteractionKind.control, "播放控制：播放 / 暂停 / 继续 / 停止"
    ),
    InteractionKind.seek: Tool(
        "seek", InteractionKind.seek, "定位场景或页面，返回全书绝对时间"
    ),
    InteractionKind.search: Tool(
        "retrieve", InteractionKind.search, "在文字层检索并返回证据框"
    ),
    InteractionKind.highlight: Tool(
        "highlight", InteractionKind.highlight, "高亮文字层片段"
    ),
    InteractionKind.click: Tool(
        "click", InteractionKind.click, "点击热区，返回对象说明"
    ),
    InteractionKind.qa: Tool(
        "qa", InteractionKind.qa, "问答链：问答卡 → 运行时 LLM → 引导"
    ),
}

# "然后/接着/之后/并且/顺便/同时" separate two instructions; a bare "再" is a
# common word inside a story sentence ("再也不想理她"), so it is not a splitter.
_SPLIT = re.compile(r"(?:然后|接着|之后|并且|顺便|同时)")
_TRIM = " ，,。;；、\t\n"
_MAX_INTENTS = 3
# "先找到……" / "请播放……"：分隔后第一段常带一个句首虚词，去掉它，
# 否则 seek 会拿 "先找到测试" 去检索文字层。
_LEAD = re.compile(
    r"^(?:先|请你|请|麻烦)(?=找到|找|看|播放|暂停|继续|停止|翻|高亮|查|搜索|打开)"
)


def describe_tools() -> list[dict[str, str]]:
    return [
        {
            "name": tool.name,
            "kind": tool.kind.value,
            "description": tool.description,
        }
        for tool in TOOLS.values()
    ]


def plan_intents(request: InteractionRequest) -> list[tuple[InteractionKind, str]]:
    """Rule plan: one intent normally, two or three when the sentence says so."""
    text = (request.input.text or "").strip()
    if request.kind is not InteractionKind.auto:
        return [(request.kind, text)]
    if not text:
        # Let `handle_interaction` produce its "no ASR text" fallback.
        return [(InteractionKind.auto, text)]

    base = interaction_kind_for(classify_instruction(text))
    parts = [part for part in (_clean(item) for item in _SPLIT.split(text)) if part]
    if len(parts) < 2:
        return [(base, text)]

    intents = [
        (interaction_kind_for(classify_instruction(part)), part)
        for part in parts[:_MAX_INTENTS]
    ]
    kinds = {kind for kind, _ in intents}
    # Two questions are still one question; only different tools make it a plan.
    if len(kinds) < 2 or kinds == {InteractionKind.qa}:
        return [(base, text)]
    return intents


def _clean(text: str) -> str:
    return _LEAD.sub("", text.strip(_TRIM)).strip(_TRIM)


def _stage_name(response: InteractionResponse) -> str:
    kind = response.kind
    if kind is InteractionKind.qa:
        tier = response.answer.tier if response.answer else None
        if tier is AnswerTier.strong:
            return "qa.card"
        if tier is AnswerTier.weak:
            return "qa.llm"
        if tier is AnswerTier.guide:
            return "qa.guide"
        return "qa"
    tool = TOOLS.get(kind)
    return tool.name if tool else kind.value


def _run_intent(
    request: InteractionRequest,
    kind: InteractionKind,
    text: str,
    package,
    package_root: Path | None,
    page_hint: int | None,
) -> tuple[InteractionResponse, int]:
    payload = request.model_copy(deep=True)
    payload.kind = kind
    payload.input.text = text
    if page_hint is not None:
        # After a seek/first question, the next tool works on the page we landed
        # on, not on the page the child was on when the recording started.
        payload.input.page_index = page_hint
        payload.context.last_page_index = page_hint
    started = time.perf_counter()
    response = TOOLS.get(kind, TOOLS[InteractionKind.qa]).run(
        payload, package, package_root
    )
    return response, int((time.perf_counter() - started) * 1000)


def _landed_page(response: InteractionResponse) -> int | None:
    if response.answer and response.answer.evidence:
        return response.answer.evidence[0].page_index
    return None


def _merge(
    responses: list[InteractionResponse],
    request_id: str,
    total_ms: int,
) -> InteractionResponse:
    answers = [item.answer for item in responses if item.answer is not None]
    last_answer = answers[-1] if answers else None
    action = next(
        (
            item.action
            for item in reversed(responses)
            if item.action is not None and item.action.type is not ActionType.none
        ),
        InteractionAction(),
    )

    evidence = []
    seen: set[tuple] = set()
    for response in responses:
        if response.answer is None:
            continue
        for entry in response.answer.evidence:
            key = (entry.page_index, entry.span_id, entry.quote, entry.bbox_px)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(entry)

    ok = any(response.status == "ok" for response in responses)
    merged = InteractionResponse(
        request_id=request_id,
        book_id=responses[0].book_id,
        session_id=responses[0].session_id,
        kind=responses[-1].kind,
        action=action,
        answer=(
            AnswerPayload(
                text="\n\n".join(
                    answer.text for answer in answers if answer and answer.text
                ),
                audio_path=last_answer.audio_path if last_answer else None,
                language=last_answer.language if last_answer else None,
                tier=last_answer.tier if last_answer else None,
                evidence=evidence,
                scene_id=(
                    last_answer.scene_id if last_answer and last_answer.scene_id else action.scene_id
                ),
                time_ms=(
                    last_answer.time_ms if last_answer and last_answer.time_ms is not None else action.time_ms
                ),
            )
            if answers
            else None
        ),
        latency=LatencyBreakdown(
            route=sum(response.latency.route or 0 for response in responses),
            retrieve=sum(response.latency.retrieve or 0 for response in responses),
            generate=sum(response.latency.generate or 0 for response in responses),
            total=total_ms,
        ),
        status="ok" if ok else "fallback",
        error=None
        if ok
        else next(
            (
                response.error
                for response in reversed(responses)
                if response.error is not None
            ),
            None,
        ),
    )
    return merged


def _record(
    request: InteractionRequest,
    response: InteractionResponse,
    *,
    data_root: Path | None,
    input_text: str | None,
    input_audio: str | None,
    intents: list[tuple[InteractionKind, str]],
    stages: list[TraceStage],
) -> None:
    now = datetime.now().astimezone()
    turn = Turn(
        turn_id=response.request_id,
        session_id=response.session_id,
        book_id=response.book_id,
        ts=now,
        input_audio=input_audio,
        input_text=input_text if input_text is not None else request.input.text,
        kind=response.kind,
        tier=response.answer.tier if response.answer else None,
        reply_text=response.answer.text if response.answer else None,
        reply_audio=response.answer.audio_path if response.answer else None,
        evidence=response.answer.evidence if response.answer else [],
        video_time=response.action.time_ms,
        latency=response.latency,
    )
    write_turn(turn, data_root)

    trace = Trace(
        trace_id=response.request_id,
        kind="interaction",
        input={
            "book_id": response.book_id,
            "session_id": response.session_id,
            "requested_kind": request.kind.value,
            "text": input_text if input_text is not None else request.input.text,
            "intents": [
                {"kind": kind.value, "text": text} for kind, text in intents
            ],
            "page_index": request.input.page_index,
        },
        stages=stages,
        result={
            "status": response.status,
            "kind": response.kind.value,
            "tier": response.answer.tier.value
            if response.answer and response.answer.tier
            else None,
            "action": response.action.model_dump(mode="json"),
            "answer": response.answer.text if response.answer else None,
            "evidence_count": len(response.answer.evidence)
            if response.answer
            else 0,
        },
        latency_ms=response.latency.total,
        created_at=now,
    )
    write_trace(trace, data_root)


def _answer_audio_enabled(requested: bool | None, input_audio: str | None) -> bool:
    if requested is not None:
        return requested
    mode = os.environ.get("DREAMYTALE_ANSWER_TTS", "voice").strip().lower()
    if mode == "always":
        return True
    if mode == "voice":
        return bool(input_audio)
    return False


def _attach_answer_audio(
    response: InteractionResponse,
    request: InteractionRequest,
    package_root: Path | None,
    *,
    enabled: bool,
    stages: list[TraceStage],
) -> None:
    if (
        not enabled
        or package_root is None
        or response.answer is None
        or not response.answer.text
        or response.answer.audio_path
    ):
        return
    started = time.perf_counter()
    audio = synthesize_answer(
        package_root,
        response.answer.text,
        response.answer.language or request.input.language,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    if not audio:
        stages.append(TraceStage(name="tts", ms=elapsed, ok=False))
        return
    response.answer.audio_path = audio
    response.latency.tts = elapsed
    response.latency.total += elapsed
    stages.append(TraceStage(name="tts", ms=elapsed, ok=True))


def run_interaction(
    request: InteractionRequest,
    package,
    package_root: Path | None = None,
    *,
    data_root: Path | None = None,
    input_text: str | None = None,
    input_audio: str | None = None,
    asr_ms: int | None = None,
    answer_audio: bool | None = None,
) -> InteractionResponse:
    """Run one request end-to-end, persist Turn + Trace, and return the answer."""
    started = time.perf_counter()
    request_id = request.request_id or f"req-{uuid.uuid4().hex[:12]}"

    plan_started = time.perf_counter()
    intents = plan_intents(request)
    route_ms = int((time.perf_counter() - plan_started) * 1000)

    stages: list[TraceStage] = []
    if asr_ms is not None:
        stages.append(TraceStage(name="asr", ms=int(asr_ms), ok=True))
    stages.append(TraceStage(name="route", ms=route_ms, ok=True))

    responses: list[InteractionResponse] = []
    page_hint = request.input.page_index or request.context.last_page_index
    for kind, text in intents:
        response, elapsed = _run_intent(
            request, kind, text, package, package_root, page_hint
        )
        responses.append(response)
        stages.append(
            TraceStage(
                name=_stage_name(response),
                ms=elapsed,
                ok=response.status != "error",
            )
        )
        landed = _landed_page(response)
        if landed is not None:
            page_hint = landed

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    merged = (
        responses[0]
        if len(responses) == 1
        else _merge(responses, request_id=request_id, total_ms=elapsed_ms)
    )
    merged.request_id = request_id

    # ASR happens before the conductor starts; the contract latency is
    # end-to-end, so add it back into the turn/trace numbers.
    if asr_ms is not None:
        merged.latency.asr = int(asr_ms)
        merged.latency.total = elapsed_ms + int(asr_ms)

    _attach_answer_audio(
        merged,
        request,
        package_root,
        enabled=_answer_audio_enabled(answer_audio, input_audio),
        stages=stages,
    )

    _record(
        request,
        merged,
        data_root=data_root,
        input_text=input_text,
        input_audio=input_audio,
        intents=intents,
        stages=stages,
    )
    return merged


def run_low_confidence(
    request: InteractionRequest,
    package,
    package_root: Path | None,
    *,
    transcript: str,
    confidence: float | None,
    asr_ms: int,
    input_audio: str | None = "upload://current-audio",
    data_root: Path | None = None,
    answer_audio: bool | None = None,
) -> InteractionResponse:
    """Do not guess when ASR is unsure: say what was heard and ask again."""
    started = time.perf_counter()
    request_id = request.request_id or f"req-{uuid.uuid4().hex[:12]}"
    language = request.input.language or (
        package.language if package is not None else None
    )
    spoken = str(transcript or "").strip()
    if language and language.lower().startswith("en"):
        message = (
            f'I heard “{spoken}”, but I am not sure I caught it. '
            "Could you say it again, or type the question?"
        )
    else:
        message = (
            f"我听到的是“{spoken}”，但不太确定。"
            "请再说一遍，或者直接把问题打出来。"
        )
    response = InteractionResponse(
        request_id=request_id,
        book_id=request.book_id,
        session_id=request.session_id,
        kind=InteractionKind.qa,
        action=InteractionAction(type=ActionType.none),
        answer=AnswerPayload(
            text=message,
            language=language,
            tier=AnswerTier.guide,
            evidence=[],
        ),
        transcript=spoken,
        latency=LatencyBreakdown(asr=int(asr_ms), route=1, total=int(asr_ms) + 1),
        status="fallback",
        error=ErrorInfo(
            code="low_confidence_asr",
            message=message,
            retryable=True,
        ),
    )
    stages = [
        TraceStage(name="asr", ms=int(asr_ms), ok=True),
        TraceStage(name="confirm", ms=1, ok=True),
    ]
    _attach_answer_audio(
        response,
        request,
        package_root,
        enabled=_answer_audio_enabled(answer_audio, input_audio),
        stages=stages,
    )
    response.latency.total = max(
        response.latency.total, int((time.perf_counter() - started) * 1000)
    )
    _record(
        request,
        response,
        data_root=data_root,
        input_text=spoken,
        input_audio=input_audio,
        intents=[(InteractionKind.qa, spoken)],
        stages=stages,
    )
    return response
