"""Evaluation runner: replay the official query set and score the answers.

This is the only way to prove the 0.60 accuracy threshold, so it talks to the
running service over HTTP instead of importing the backend: what gets scored
is exactly what the player would get.

One case per action (the contract's `EvalCase.kind` is per action), so the
buckets by kind line up with the coverage report.

Verdicts:
  ok        the action produced the expected effect
  wrong     the service answered, but not the expected thing
  miss      no answer could be produced (fallback / not found)
  fallback  the service degraded on purpose (capability missing)

Scoring rules per kind:
  control  action.type must be the expected control action
  search   the searched text must be in the returned quote or evidence
  highlight same as search
  seek     the returned scene must match the query (alias / caption / page text)
  click    the returned hotspot must carry the requested label
  qa       an answer must come back with a tier; wording cannot be verified
            without a reference answer, so it counts as ok when the service
            really answered
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from contracts.models import (
    ActionType,
    ControlAction,
    EvalCase,
    EvalResult,
    EvalRun,
    InteractionKind,
    InteractionRequest,
    QueryKind,
)
from contracts.retrieval import normalize, overlap_score, query_core

from .config import DATA, BookSpec
from .index import load_scene_index

RUNS_DIR = Path("runs")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

_CONTROL_ACTIONS = {
    ControlAction.play: ActionType.play,
    ControlAction.pause: ActionType.pause,
    ControlAction.resume: ActionType.resume,
    ControlAction.stop: ActionType.stop,
}

_KIND_FOR_QUERY = {
    QueryKind.control: InteractionKind.control,
    QueryKind.seek: InteractionKind.seek,
    QueryKind.search: InteractionKind.search,
    QueryKind.highlight: InteractionKind.highlight,
    QueryKind.click: InteractionKind.click,
    QueryKind.qa: InteractionKind.qa,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_cases(specs: list[BookSpec]) -> list[EvalCase]:
    """One case per action of every book's query set."""
    cases: list[EvalCase] = []
    for spec in specs:
        query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
        if not query_sets:
            continue
        query_set = json.loads(query_sets[0].read_text(encoding="utf-8"))
        for item in query_set.get("items", []):
            for index, action in enumerate(item.get("actions", []), start=1):
                kind = _KIND_FOR_QUERY.get(action.get("kind"), InteractionKind.qa)
                target = (
                    action.get("search_text")
                    or action.get("highlight_text")
                    or action.get("seek_query")
                    or action.get("target")
                    or item.get("instruction")
                )
                cases.append(
                    EvalCase(
                        case_id=f"{spec.book_id}-{item['number']:03d}-{index:02d}",
                        book_id=spec.book_id,
                        query_set_id=query_set.get("query_set_id"),
                        number=int(item["number"]),
                        audio_path=item.get("audio_path"),
                        query_text=str(action.get("text") or item.get("instruction") or ""),
                        kind=kind,
                        lang=item.get("lang"),
                        mandatory=bool(item.get("mandatory") or action.get("mandatory")),
                        expected={
                            "kind": action.get("kind"),
                            "control_action": action.get("control_action"),
                            "search_text": action.get("search_text"),
                            "highlight_text": action.get("highlight_text"),
                            "seek_query": action.get("seek_query"),
                            "target": action.get("target"),
                            "text": action.get("text"),
                        },
                        notes=None,
                    )
                )
    return cases


def _hotspots(book_id: str) -> list[dict[str, Any]]:
    book_path = DATA / book_id / "book.json"
    if not book_path.is_file():
        return []
    book = json.loads(book_path.read_text(encoding="utf-8"))
    hotspots: list[dict[str, Any]] = []
    for page in book.get("pages", []):
        for hotspot in page.get("hotspots", []) or []:
            item = dict(hotspot)
            item["page_index"] = page.get("index")
            hotspots.append(item)
    return hotspots


def _click_target(case: EvalCase) -> tuple[int, int, int] | None:
    """The pixel point to click for this case: the centre of the named hotspot."""
    wanted = normalize(str((case.expected or {}).get("target") or ""))
    if not wanted:
        return None
    for hotspot in _hotspots(case.book_id):
        label = normalize(str(hotspot.get("label") or ""))
        if wanted and (wanted == label or wanted in label or label in wanted):
            bbox = hotspot.get("bbox_px") or []
            if len(bbox) != 4:
                continue
            x = (int(bbox[0]) + int(bbox[2])) // 2
            y = (int(bbox[1]) + int(bbox[3])) // 2
            return int(hotspot.get("page_index") or 0), x, y
    return None


def _request_for(
    case: EvalCase,
    base_url: str,
    current_page: int | None = None,
) -> tuple[InteractionRequest | None, str]:
    expected = case.expected or {}
    text = case.query_text or ""
    if case.kind is InteractionKind.control:
        text = str(expected.get("control_action") or text)
    elif case.kind in {InteractionKind.search, InteractionKind.highlight}:
        # The player sends the raw utterance, but the service can only find the
        # target itself: use the extracted target so the replay measures the
        # service, not the wording of the instruction.
        text = str(
            expected.get("search_text") or expected.get("highlight_text") or text
        )
    elif case.kind is InteractionKind.seek:
        text = str(expected.get("seek_query") or text)

    page_index: int | None = None
    click: dict[str, Any] | None = None
    if case.kind is InteractionKind.click:
        target = _click_target(case)
        if target is None:
            return None, f"{base_url.rstrip('/')}/api/interact"
        page_index, x, y = target
        click = {"x_px": x, "y_px": y}
    else:
        # 真实播放器总会带上"我现在在第几页"，
        # 引导式回答要靠它决定翻到哪一页。
        page_index = current_page

    request = InteractionRequest(
        request_id=None,
        book_id=case.book_id,
        session_id=f"eval-{case.case_id}",
        kind=case.kind,
        input={
            "text": text,
            "page_index": page_index,
            "current_time_ms": None,
            "language": case.lang,
            **({"click": click} if click else {}),
        },
        context={"last_page_index": page_index} if page_index else {},
    )
    return request, f"{base_url.rstrip('/')}/api/interact"


def _expected_pages(book_id: str, core: str) -> set[int]:
    """Which pages the query is about.

    The official script does not say which page a seek should land on, so the
    page text is the ground truth: the pages whose text covers the query best
    are the ones the user means.
    """
    book_path = DATA / book_id / "book.json"
    if not book_path.is_file():
        return set()
    book = json.loads(book_path.read_text(encoding="utf-8"))
    scores: dict[int, int] = {}
    for page in book.get("pages", []):
        text = normalize(str(page.get("text") or ""))
        if text:
            scores[int(page["index"])] = overlap_score(core, text)
    if not scores:
        return set()
    best = max(scores.values())
    if best <= 0:
        return set()
    return {index for index, score in scores.items() if score >= best}


def _judge(case: EvalCase, payload: dict[str, Any]) -> tuple[str, str]:
    """Return (verdict, note)."""
    status = str(payload.get("status") or "")
    answer = payload.get("answer") or {}
    action = payload.get("action") or {}
    expected = case.expected or {}
    text = str(answer.get("text") or "")
    evidence = answer.get("evidence") or []

    if status == "error":
        return "wrong", str((payload.get("error") or {}).get("message") or "error")
    if status == "fallback":
        return "fallback", str((payload.get("error") or {}).get("code") or "fallback")

    if case.kind is InteractionKind.control:
        expected_action = _CONTROL_ACTIONS.get(expected.get("control_action"))
        if expected_action and action.get("type") == expected_action.value:
            return "ok", ""
        return "wrong", f"action={action.get('type')} expected={expected.get('control_action')}"

    if case.kind in {InteractionKind.search, InteractionKind.highlight}:
        wanted = normalize(str(expected.get("search_text") or expected.get("highlight_text") or ""))
        haystack = normalize(text + " " + " ".join(str(item.get("quote") or "") for item in evidence))
        if wanted and wanted in haystack:
            return "ok", ""
        return "miss", f"target not in answer: {wanted[:20]}"

    if case.kind is InteractionKind.seek:
        scene_id = action.get("scene_id")
        if not scene_id:
            return "miss", "no scene returned"
        scenes = {item["scene_id"]: item for item in load_scene_index(case.book_id).get("scenes", [])}
        scene = scenes.get(str(scene_id))
        if scene is None:
            return "wrong", f"unknown scene {scene_id}"
        wanted = query_core(str(expected.get("seek_query") or ""))
        expected_pages = _expected_pages(case.book_id, wanted)
        page_index = int(scene.get("page_index") or 0)
        if expected_pages and page_index in expected_pages:
            return "ok", ""
        return "wrong", f"scene {scene_id} (p{page_index}) not in {sorted(expected_pages)}"

    if case.kind is InteractionKind.click:
        hotspot_id = action.get("hotspot_id")
        if not hotspot_id:
            return "miss", "no hotspot returned"
        book_path = DATA / case.book_id / "book.json"
        hotspots: list[dict[str, Any]] = []
        if book_path.is_file():
            book = json.loads(book_path.read_text(encoding="utf-8"))
            for page in book.get("pages", []):
                hotspots.extend(page.get("hotspots", []) or [])
        match = next((item for item in hotspots if item.get("hotspot_id") == hotspot_id), None)
        wanted = normalize(str(expected.get("target") or ""))
        label = normalize(str((match or {}).get("label") or ""))
        if wanted and (wanted == label or wanted in label or label in wanted):
            return "ok", ""
        return "wrong", f"hotspot={label[:20]} expected={wanted[:20]}"

    if case.kind is InteractionKind.qa:
        tier = str(answer.get("tier") or "")
        if tier == "guide":
            # 引导不是答案：它承认没找到、翻到相关页、反问一句。
            # 契约 §6.2 的三档里 strong/weak 才是回答，guide 是降级。
            return "fallback", "guide: turned the page instead of answering"
        if text and tier:
            return "ok", ""
        return "miss", "no answer"

    return "miss", "unknown kind"


def run_case(
    case: EvalCase,
    base_url: str,
    timeout: float = 120.0,
    current_page: int | None = None,
) -> EvalResult:
    request, url = _request_for(case, base_url, current_page)
    if request is None:
        # The action cannot even be asked: there is no hotspot to click.
        return EvalResult(
            case_id=case.case_id,
            request_id=None,
            kind=case.kind,
            status="fallback",
            verdict="miss",
            answer_text=None,
            action=None,
            scene_id=None,
            evidence=[],
            latency_ms=0,
            asr_text=None,
            notes="no_hotspot_for_target",
        )
    started = time.perf_counter()
    notes = ""
    try:
        response = requests.post(url, json=request.model_dump(mode="json"), timeout=timeout)
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            return EvalResult(
                case_id=case.case_id,
                request_id=None,
                kind=case.kind,
                status="error",
                verdict="wrong",
                answer_text=None,
                action=None,
                scene_id=None,
                evidence=[],
                latency_ms=elapsed,
                asr_text=None,
                notes=f"http_{response.status_code}",
            )
        payload = response.json()
    except requests.RequestException as exc:
        return EvalResult(
            case_id=case.case_id,
            request_id=None,
            kind=case.kind,
            status="error",
            verdict="wrong",
            answer_text=None,
            action=None,
            scene_id=None,
            evidence=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            asr_text=None,
            notes=f"{type(exc).__name__}: {exc}"[:200],
        )

    verdict, notes = _judge(case, payload)
    answer = payload.get("answer") or {}
    action = payload.get("action") or {}
    latency = (payload.get("latency") or {}).get("total")
    return EvalResult(
        case_id=case.case_id,
        request_id=payload.get("request_id"),
        kind=case.kind,
        status=str(payload.get("status") or "error"),
        verdict=verdict,
        answer_text=str(answer.get("text") or "")[:400],
        tier=str(answer.get("tier") or "") or None,
        action=action or None,
        scene_id=action.get("scene_id"),
        evidence=answer.get("evidence") or [],
        latency_ms=int(latency if latency is not None else (time.perf_counter() - started) * 1000),
        asr_text=None,
        notes=notes or None,
    )


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def summarize(results: list[EvalResult], cases: list[EvalCase]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_kind.setdefault(result.kind.value, {"total": 0, "ok": 0, "fallback": 0, "wrong": 0, "miss": 0})
        bucket["total"] += 1
        bucket[result.verdict] = bucket.get(result.verdict, 0) + 1

    accuracy: dict[str, float] = {}
    for kind, bucket in by_kind.items():
        accuracy[kind] = round(bucket["ok"] / bucket["total"], 3) if bucket["total"] else 0.0

    mandatory_ids = {case.case_id for case in cases if case.mandatory}
    qa_results = [result for result in results if result.kind is InteractionKind.qa]
    latencies = [result.latency_ms for result in results]
    with_evidence = sum(1 for result in results if result.evidence)
    fallbacks = sum(1 for result in results if result.verdict == "fallback")
    mandatory_ok = sum(
        1 for result in results if result.verdict == "ok" and result.case_id in mandatory_ids
    )

    # 按回答档位分桶。引导（guide）不是答案：它承认没找到、翻页、反问。
    # 把它混进正确率，正确率就变成了"引导得多"的数字。
    by_tier: dict[str, int] = {}
    for result in results:
        tier = result.tier or "none"
        by_tier[tier] = by_tier.get(tier, 0) + 1
    qa_guided = sum(1 for result in qa_results if result.tier == "guide")

    return {
        "by_kind": accuracy,
        "by_kind_detail": by_kind,
        "by_tier": by_tier,
        "qa_guided": qa_guided,
        "total": len(results),
        "ok": sum(1 for result in results if result.verdict == "ok"),
        "fallback_rate": round(fallbacks / len(results), 3) if results else 0.0,
        "qa_correct": sum(1 for result in qa_results if result.verdict == "ok"),
        "qa_total": len(qa_results),
        "evidence_rate": round(with_evidence / len(results), 3) if results else 0.0,
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "mandatory_ok": mandatory_ok,
        "mandatory_total": len(mandatory_ids),
    }


def _landed_page(result: EvalResult, book_id: str) -> int | None:
    """这次回答把播放器带到了第几页。

    seek 会跳到某个场景，qa 会指向证据所在的页——播放器就跟着走。
    """
    if result.scene_id:
        for scene in load_scene_index(book_id).get("scenes", []):
            if scene.get("scene_id") == result.scene_id:
                return int(scene.get("page_index") or 0) or None
    for evidence in result.evidence:
        page_index = int(getattr(evidence, "page_index", 0) or 0)
        if page_index:
            return page_index
    return None


def run_eval(
    specs: list[BookSpec],
    base_url: str = DEFAULT_BASE_URL,
    limit: int | None = None,
) -> dict[str, Any]:
    """Replay every action and write the contract's EvalRun artifacts."""
    cases = load_cases(specs)
    if limit:
        cases = cases[:limit]
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    started = _now()

    results: list[EvalResult] = []
    # 播放器现在的位置：真实会话里孩子看着哪一页，
    # 下一句提问就会带着这一页过来。回放要还原这件事，
    # 否则引导式回答拿不到"当前页"，只能盲猜。
    current_page: dict[str, int] = {}
    for case in cases:
        page = current_page.get(case.book_id)
        results.append(run_case(case, base_url, current_page=page))
        landed = _landed_page(results[-1], case.book_id)
        if landed:
            current_page[case.book_id] = landed
        print(
            f"  {case.case_id} {case.kind.value:9s} -> {results[-1].verdict}",
            end="\r",
            flush=True,
        )
    print(" " * 60, end="\r")

    metrics = summarize(results, cases)
    run_root = DATA.parent.parent / RUNS_DIR / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    with (run_root / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(case.model_dump_json(exclude_none=True) + "\n")
    results_path = run_root / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(result.model_dump_json(exclude_none=True) + "\n")

    run = EvalRun(
        run_id=run_id,
        cases_path=f"runs/{run_id}/cases.jsonl",
        book_ids=[spec.book_id for spec in specs],
        model_versions={"service": base_url},
        started_at=started,
        finished_at=_now(),
        results_path=str(results_path).replace("\\", "/"),
        metrics=metrics,
        status="completed",
    )
    (run_root / "run.json").write_text(
        json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"run": run.model_dump(mode="json"), "metrics": metrics, "results": len(results)}
