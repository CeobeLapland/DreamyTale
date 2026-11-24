"""交互协议实现（契约 §9）。

后端目前没有接入 ASR / LLM / TTS，所以只有不依赖模型的动作能给出真实结果：
播放控制、基于文字层的检索、高亮、点击命中热区。其余一律返回 `status="fallback"`
的引导式回答，契约明确不允许用占位答案伪装成功。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from threading import Lock

from contracts.retrieval import extract_target as _extract_target
from contracts.retrieval import find_scene as _find_scene
from contracts.retrieval import search_index as _search_index

from backend.app.models import (
    ActionType,
    AnswerPayload,
    AnswerTier,
    BookPackage,
    ClickPoint,
    ControlAction,
    ErrorInfo,
    Evidence,
    Hotspot,
    InteractionAction,
    InteractionKind,
    InteractionRequest,
    InteractionResponse,
    LatencyBreakdown,
    QueryKind,
    TextSpan,
)
from backend.app.script_parser import classify_instruction, control_action_for
from backend.app.guide import build_guide_answer, page_start_times
from backend.app.knowledge import find_qa_card, load_qa_cards
from backend.app.llm_answer import build_llm_answer
from pipeline.annotations import (
    active_annotations,
    apply_annotations_to_cards,
    apply_annotations_to_package,
)

INDEX_DIR = Path("derived") / "index"

# 一轮会话里"这句话/它"指代的对象。契约 §9.1 的 session_id 就是为这个存在的。
# 只放在内存里：进程重启后丢失比写错好，前端下次会重新说出目标。
_SESSION_TARGETS: dict[str, str] = {}
_SESSION_LOCK = Lock()
_SESSION_LIMIT = 512

_PRONOUNS = ("这句话", "这一句", "这句", "那句话", "那句話", "this sentence", "that sentence")
_PRONOUN_WORDS = {"这句话", "这句", "那个", "这个", "它", "this", "that"}


def _last_target(session_id: str) -> str | None:
    with _SESSION_LOCK:
        return _SESSION_TARGETS.get(session_id)


def _remember_target(session_id: str, target: str) -> None:
    if not target:
        return
    with _SESSION_LOCK:
        if len(_SESSION_TARGETS) >= _SESSION_LIMIT:
            _SESSION_TARGETS.clear()
        _SESSION_TARGETS[session_id] = target


def _resolve_target(session_id: str, text: str) -> str:
    """"高亮这句话" -> 上一轮真正查找的那段文字。"""
    target = _extract_target(text) or text
    points_back = any(phrase in (text or "").lower() for phrase in _PRONOUNS)
    if not target or points_back or target.lower() in _PRONOUN_WORDS:
        return _last_target(session_id) or target
    return target


def _load_index(package_root: Path | None, name: str) -> dict:
    """读 pipeline 产出的索引；没有索引时返回空结构。"""
    if package_root is None:
        return {}
    path = package_root / INDEX_DIR / name
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# 每个 kind 退化时给用户看的说明；写清楚"缺什么"，不要伪装成答案。
_GUIDE_TEXT = {
    InteractionKind.qa: "还没有接入语音识别与问答模型，无法直接回答这个问题；可以先翻到相关画面再提问。",
    InteractionKind.seek: "还没有生成场景时间轴，暂时无法定位到具体画面。",
    InteractionKind.click: "这个位置没有命中任何热区。",
    InteractionKind.search: "这本书的文字层里没有找到要找的内容。",
    InteractionKind.highlight: "这本书的文字层里没有找到要高亮的内容。",
    InteractionKind.control: "没有识别出播放控制指令。",
}

_KIND_ERROR_CODES = {
    InteractionKind.qa: "qa_runtime_not_configured",
    InteractionKind.seek: "scene_plan_not_generated",
    InteractionKind.click: "hotspot_not_resolved",
    InteractionKind.search: "text_not_found",
    InteractionKind.highlight: "text_not_found",
    InteractionKind.control: "control_not_understood",
}


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def _find_text(
    package: BookPackage,
    target: str,
) -> list[tuple[int, list[TextSpan], str]]:
    """在包的文字层里找目标文本，返回 (页码, 命中的 span, 命中片段)。"""
    needle = _normalize(target)
    if not needle:
        return []
    hits: list[tuple[int, list[TextSpan], str]] = []
    for page in package.pages:
        matched: list[TextSpan] = []
        for span in page.text_spans:
            if needle in _normalize(span.text):
                matched.append(span)
        if matched:
            hits.append((page.index, matched, matched[0].text))
            continue
        if needle in _normalize(page.text):
            hits.append((page.index, [], page.text))
    return hits


def _click_target(
    package: BookPackage,
    page_index: int | None,
    click: ClickPoint,
) -> Hotspot | None:
    if page_index is None:
        return None
    page = next((item for item in package.pages if item.index == page_index), None)
    if page is None:
        return None
    for hotspot in page.hotspots:
        x1, y1, x2, y2 = hotspot.bbox_px
        if click.x_px is not None and click.y_px is not None:
            if x1 <= click.x_px < x2 and y1 <= click.y_px < y2:
                return hotspot
            continue
        if click.x_norm is not None and click.y_norm is not None:
            width = page.width_px or 1
            height = page.height_px or 1
            x_px = click.x_norm * width
            y_px = click.y_norm * height
            if x1 <= x_px < x2 and y1 <= y_px < y2:
                return hotspot
    return None


def _fallback(
    request: InteractionRequest,
    kind: InteractionKind,
    *,
    request_id: str,
    route_ms: int,
    total_ms: int,
    message: str | None = None,
) -> InteractionResponse:
    text = message or _GUIDE_TEXT.get(kind, "该交互暂不可用。")
    return InteractionResponse(
        request_id=request_id,
        book_id=request.book_id,
        session_id=request.session_id,
        kind=kind,
        action=InteractionAction(type=ActionType.none),
        answer=AnswerPayload(
            text=text,
            language=request.input.language or request.context.last_lang,
            tier=AnswerTier.guide,
            evidence=[],
        ),
        latency=LatencyBreakdown(route=route_ms, total=total_ms),
        status="fallback",
        error=ErrorInfo(
            code=_KIND_ERROR_CODES.get(kind, "interaction_not_available"),
            message=text,
            retryable=False,
        ),
    )


def _response(
    request: InteractionRequest,
    kind: InteractionKind,
    *,
    request_id: str,
    action: InteractionAction,
    answer: AnswerPayload | None,
    status: str,
    route_ms: int,
    total_ms: int,
    error: ErrorInfo | None = None,
) -> InteractionResponse:
    return InteractionResponse(
        request_id=request_id,
        book_id=request.book_id,
        session_id=request.session_id,
        kind=kind,
        action=action,
        answer=answer,
        latency=LatencyBreakdown(route=route_ms, total=total_ms),
        status=status,
        error=error,
    )


def handle_interaction(
    request: InteractionRequest,
    package: BookPackage | None,
    package_root: Path | None = None,
) -> InteractionResponse:
    """把一次交互请求变成契约 §9.2 的响应。"""
    started = time.perf_counter()
    # 客户端可以自带 request_id 便于前端关联；服务端不据此做去重或幂等。
    request_id = request.request_id or f"req-{uuid.uuid4().hex[:12]}"

    # Human corrections are an overlay: the auto BookPackage on disk is never
    # edited. Applied before any click/search/qa reads the package.
    annotations: dict = {}
    if package is not None and package_root is not None:
        annotations = active_annotations(package.book_id, package_root)
        if annotations:
            package = apply_annotations_to_package(
                package, annotations, package_root=package_root
            )

    route_started = time.perf_counter()
    kind = request.kind
    text = (request.input.text or "").strip()
    if kind is InteractionKind.auto:
        if not text:
            return _fallback(
                request,
                InteractionKind.qa,
                request_id=request_id,
                route_ms=0,
                total_ms=int((time.perf_counter() - started) * 1000),
                message="只有语音输入时还没有接入语音识别，无法判断意图。",
            )
        kind = interaction_kind_for(classify_instruction(text))

    # Routing ends here; answer/search latency belongs to `retrieve`/`generate`,
    # not to `route`. Measuring it at return time would double count the model.
    route_ms = int((time.perf_counter() - route_started) * 1000)

    if kind is InteractionKind.control:
        control = _control_action(text)
        if control is None:
            return _fallback(
                request,
                kind,
                request_id=request_id,
                route_ms=route_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
            )
        return _response(
            request,
            kind,
            request_id=request_id,
            action=InteractionAction(type=control),
            answer=None,
            status="ok",
            route_ms=route_ms,
            total_ms=int((time.perf_counter() - started) * 1000),
        )

    if kind in {InteractionKind.search, InteractionKind.highlight}:
        # The player sends the whole utterance ("高亮文字“bats”"); the service
        # needs the target itself, otherwise it searches for the sentence.
        target = _resolve_target(request.session_id, text)
        entries = _search_index(_load_index(package_root, "search_index.json"), target)
        if entries:
            _remember_target(request.session_id, target)
            evidence = [
                Evidence(
                    page_index=int(entry.get("page_index") or 0),
                    bbox_px=tuple(entry["bbox_px"]) if entry.get("bbox_px") else None,
                    span_id=entry.get("span_id") or entry.get("entry_id"),
                    quote=str(entry.get("text") or ""),
                )
                for entry in entries[:3]
            ]
            span_ids = [
                str(entry.get("entry_id"))
                for entry in entries
                if entry.get("kind") == "span"
            ]
            return _response(
                request,
                kind,
                request_id=request_id,
                action=InteractionAction(type=ActionType.highlight, span_ids=span_ids),
                answer=AnswerPayload(
                    text=str(entries[0].get("text") or ""),
                    language=package.language if package else None,
                    tier=AnswerTier.quote,
                    evidence=evidence,
                    scene_id=entries[0].get("scene_id"),
                    time_ms=entries[0].get("start_ms"),
                ),
                status="ok",
                route_ms=route_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
            )
        if package is not None:
            hits = _find_text(package, target)
            if hits:
                _remember_target(request.session_id, target)
                page_index, spans, quote = hits[0]
                span_ids = [span.span_id for span in spans]
                evidence = [
                    Evidence(
                        page_index=page_index,
                        bbox_px=tuple(span.bbox_px),
                        span_id=span.span_id,
                        quote=span.text,
                    )
                    for span in spans[:3]
                ]
                return _response(
                    request,
                    kind,
                    request_id=request_id,
                    action=InteractionAction(type=ActionType.highlight, span_ids=span_ids),
                    answer=AnswerPayload(
                        text=quote,
                        language=package.language,
                        tier=AnswerTier.quote,
                        evidence=evidence,
                        scene_id=None,
                        time_ms=None,
                    ),
                    status="ok",
                    route_ms=route_ms,
                    total_ms=int((time.perf_counter() - started) * 1000),
                )
        return _fallback(
            request,
            kind,
            request_id=request_id,
            route_ms=route_ms,
            total_ms=int((time.perf_counter() - started) * 1000),
        )

    if kind is InteractionKind.seek:
        scene_index = _load_index(package_root, "scene_index.json")
        scene = _find_scene(scene_index, text)
        if scene is None:
            # 语音没有引号："找到还不倒" 里的 "还不倒" 可能是文字而不是画面。
            # 用去掉指令词后的短目标再试一次，不额外发明内容。
            target = _extract_target(text)
            if target and target != text:
                scene = _find_scene(scene_index, target)
        if scene:
            # Scene.start_ms 是相对页面的，播放器要的是全书绝对时间。
            # 不换算的话每次定位都落在第 0 毫秒，也就是第一页。
            page_start = page_start_times(package_root).get(
                int(scene.get("page_index") or 0), 0
            )
            seek_ms = page_start + int(scene.get("start_ms") or 0)
            return _response(
                request,
                kind,
                request_id=request_id,
                action=InteractionAction(
                    type=ActionType.seek,
                    scene_id=str(scene.get("scene_id") or ""),
                    time_ms=seek_ms,
                ),
                answer=AnswerPayload(
                    text=str(scene.get("caption") or ""),
                    language=package.language if package else None,
                    tier=AnswerTier.quote,
                    evidence=[
                        Evidence(
                            page_index=int(scene.get("page_index") or 0),
                            quote=str(scene.get("caption") or ""),
                        )
                    ],
                    scene_id=str(scene.get("scene_id") or ""),
                    time_ms=seek_ms,
                ),
                status="ok",
                route_ms=route_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
            )

        # 场景索引没命中，但这段文字确实在书里：翻到那一页并引用它。
        # 这仍然不是"猜一页"——页码来自文字命中。
        target = _extract_target(text) or text
        if package is not None and target:
            hits = _find_text(package, target)
            if hits:
                page_index, spans, quote = hits[0]
                seek_ms = page_start_times(package_root).get(page_index, 0)
                evidence = [
                    Evidence(
                        page_index=page_index,
                        bbox_px=tuple(span.bbox_px),
                        span_id=span.span_id,
                        quote=span.text,
                    )
                    for span in spans[:3]
                ] or [Evidence(page_index=page_index, quote=quote)]
                return _response(
                    request,
                    kind,
                    request_id=request_id,
                    action=InteractionAction(type=ActionType.seek, time_ms=seek_ms),
                    answer=AnswerPayload(
                        text=quote,
                        language=package.language,
                        tier=AnswerTier.quote,
                        evidence=evidence,
                        time_ms=seek_ms,
                    ),
                    status="ok",
                    route_ms=route_ms,
                    total_ms=int((time.perf_counter() - started) * 1000),
                )
        return _fallback(
            request,
            kind,
            request_id=request_id,
            route_ms=route_ms,
            total_ms=int((time.perf_counter() - started) * 1000),
        )

    if kind is InteractionKind.click:
        page_index = request.input.page_index or request.context.last_page_index
        hotspot = None
        if package is not None and request.input.click is not None:
            hotspot = _click_target(package, page_index, request.input.click)
        if hotspot is None:
            return _fallback(
                request,
                kind,
                request_id=request_id,
                route_ms=route_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
            )
        return _response(
            request,
            kind,
            request_id=request_id,
            action=InteractionAction(type=ActionType.none, hotspot_id=hotspot.hotspot_id),
            answer=AnswerPayload(
                text=hotspot.description,
                language=package.language if package else None,
                tier=AnswerTier.quote,
                evidence=[
                    Evidence(
                        page_index=hotspot.page_index,
                        bbox_px=tuple(hotspot.bbox_px),
                        quote=hotspot.label,
                    )
                ],
            ),
            status="ok",
            route_ms=route_ms,
            total_ms=int((time.perf_counter() - started) * 1000),
        )

    if kind is InteractionKind.qa:
        if package_root is not None and text:
            cards = load_qa_cards(package_root)
            if annotations and package is not None:
                cards = apply_annotations_to_cards(
                    cards,
                    annotations,
                    book_id=package.book_id,
                    package_root=package_root,
                )
            match = find_qa_card(cards, text, request.input.language)
            if match is not None:
                card = match.card
                anchor = card.video_anchor
                scene_id = anchor.scene_id if anchor else None
                time_ms = anchor.start_ms if anchor else None
                return _response(
                    request,
                    kind,
                    request_id=request_id,
                    action=InteractionAction(
                        type=ActionType.show_card,
                        scene_id=scene_id,
                        time_ms=time_ms,
                    ),
                    answer=AnswerPayload(
                        text=match.answer,
                        language=request.input.language,
                        tier=match.tier,
                        evidence=list(card.evidence),
                        scene_id=scene_id,
                        time_ms=time_ms,
                    ),
                    status="ok",
                    route_ms=route_ms,
                    total_ms=int(
                        (time.perf_counter() - started) * 1000
                    ),
                )

        # 没有命中卡片时，先让运行时 LLM 只依据书内上下文试答一次。
        # 答不上（或没有模型）再退回 guide；不允许编造。
        if package is not None and package_root is not None and text:
            llm_answer = build_llm_answer(
                package,
                package_root,
                text,
                request.input.language or package.language,
            )
            if llm_answer is not None:
                response = _response(
                    request,
                    kind,
                    request_id=request_id,
                    action=InteractionAction(
                        type=ActionType.seek,
                        scene_id=llm_answer.scene_id,
                        time_ms=llm_answer.time_ms,
                    ),
                    answer=AnswerPayload(
                        text=llm_answer.text,
                        language=request.input.language or package.language,
                        tier=AnswerTier.weak,
                        evidence=list(llm_answer.evidence),
                        scene_id=llm_answer.scene_id,
                        time_ms=llm_answer.time_ms,
                    ),
                    status="ok",
                    route_ms=route_ms,
                    total_ms=int((time.perf_counter() - started) * 1000),
                )
                response.latency.generate = llm_answer.latency_ms
                return response

        # 没有答案卡：按契约 §6.2 给引导，而不是一句"没找到"。
        # 引导必须三件事齐全——承认、翻页、反问——并且引用书里的原句。
        # 停在孩子正在看的那一页：翻到哪一页是 pipeline 在卡里定好的，
        # 运行时不该再去猜。
        if package is not None and text:
            guide = build_guide_answer(
                package,
                package_root or Path("."),
                text,
                request.input.language or package.language,
                request.input.page_index or request.context.last_page_index,
            )
            if guide is not None:
                return _response(
                    request,
                    kind,
                    request_id=request_id,
                    action=InteractionAction(
                        type=ActionType.seek,
                        scene_id=guide.scene_id,
                        time_ms=guide.time_ms,
                    ),
                    answer=AnswerPayload(
                        text=guide.text,
                        language=request.input.language or package.language,
                        tier=AnswerTier.guide,
                        evidence=list(guide.evidence),
                        scene_id=guide.scene_id,
                        time_ms=guide.time_ms,
                    ),
                    status="ok",
                    route_ms=route_ms,
                    total_ms=int(
                        (time.perf_counter() - started) * 1000
                    ),
                )

        return _fallback(
            request,
            kind,
            request_id=request_id,
            route_ms=route_ms,
            total_ms=int((time.perf_counter() - started) * 1000),
            message="没有找到对应的问答卡；可以换一种问法或先查看相关画面。",
        )

    return _fallback(
        request,
        kind,
        request_id=request_id,
        route_ms=route_ms,
        total_ms=int((time.perf_counter() - started) * 1000),
    )


def interaction_kind_for(kind: QueryKind) -> InteractionKind:
    mapping = {
        QueryKind.control: InteractionKind.control,
        QueryKind.seek: InteractionKind.seek,
        QueryKind.search: InteractionKind.search,
        QueryKind.highlight: InteractionKind.highlight,
        QueryKind.click: InteractionKind.click,
        QueryKind.qa: InteractionKind.qa,
    }
    return mapping.get(kind, InteractionKind.qa)


def _control_action(text: str) -> ActionType | None:
    action = control_action_for(text)
    if action is None:
        return None
    return {
        ControlAction.play: ActionType.play,
        ControlAction.pause: ActionType.pause,
        ControlAction.resume: ActionType.resume,
        ControlAction.stop: ActionType.stop,
    }[action]
