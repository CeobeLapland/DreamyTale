"""测试用的 v2 数据包夹具。

所有夹具都按 contracts/models.py 的 v2 结构构造，避免测试里再写一份契约。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.models import content_hash


BOOK_ID = "zh-99"
QUERY_SET_ID = "zh-99-script-v1"


def _hash(payload: dict[str, Any]) -> str:
    return content_hash(payload)


def text_span() -> dict[str, Any]:
    span = {
        "span_id": "span-zh-99-001-001",
        "page_index": 1,
        "text": "测试",
        "bbox_px": [10, 10, 50, 30],
        "source": "embedded_pdf",
        "confidence": 0.99,
        "version": 1,
        "status": "active",
    }
    span["hash"] = _hash(span)
    return span


def hotspot() -> dict[str, Any]:
    item = {
        "hotspot_id": "hotspot-zh-99-001-001",
        "page_index": 1,
        "label": "城堡",
        "bbox_px": [20, 20, 100, 100],
        "description": "测试城堡",
        "source": "manual",
        "confidence": 0.95,
        "version": 1,
        "status": "active",
    }
    item["hash"] = _hash(item)
    return item


def page() -> dict[str, Any]:
    return {
        "index": 1,
        "image_path": "pages/001.png",
        "width_px": 200,
        "height_px": 200,
        "width_pt": 100.0,
        "height_pt": 100.0,
        "text": "测试文字",
        "text_source": "embedded_pdf",
        "text_confidence": 0.99,
        "language": "zh-CN",
        "blocks": [],
        "text_spans": [text_span()],
        "hotspots": [hotspot()],
        "sha256": "0" * 64,
        "render": {"dpi": 144, "renderer": "pypdfium2", "version": "5.15.2"},
    }


def valid_package() -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "book_id": BOOK_ID,
        "source_name": "中文绘本99",
        "title": "测试绘本",
        "authors": [],
        "language": "zh-CN",
        "languages": ["zh-CN"],
        "content_type": "narrative",
        "source_type": "pdf",
        "source_path": "source/book.pdf",
        "page_count": 1,
        "pages": [page()],
        "style": None,
        "rights": {"license": "competition_sample", "note": "测试数据"},
        "status": "ingested",
        "query_set_ids": [QUERY_SET_ID],
        "capabilities_path": None,
        "created_at": "2026-11-17T06:30:00Z",
        "updated_at": "2026-11-17T06:30:00Z",
    }


def legacy_package() -> dict[str, Any]:
    """v1 形状的书包：pdf_path + script_path + steps + click_targets。"""
    return {
        "schema_version": "1.0.0",
        "book_id": BOOK_ID,
        "source_name": "中文绘本99",
        "title": "测试绘本",
        "language": "zh-CN",
        "pdf_path": "source/book.pdf",
        "script_path": "source/script.txt",
        "page_count": 1,
        "pages": [
            {
                "index": 1,
                "image_path": "pages/001.png",
                "text": "测试文字",
                "text_source": "embedded_pdf",
                "width_pt": 100.0,
                "height_pt": 100.0,
                "width_px": 200,
                "height_px": 200,
                "text_spans": [
                    {
                        "span_id": "page-001-span-001",
                        "page_index": 1,
                        "text": "测试",
                        "bbox_px": [10, 10, 50, 30],
                        "source": "embedded_pdf",
                    }
                ],
                "hotspots": [
                    {
                        "hotspot_id": "page-001-hotspot-001",
                        "page_index": 1,
                        "label": "城堡",
                        "bbox_px": [20, 20, 100, 100],
                        "description": "测试城堡",
                        "source": "manual",
                    }
                ],
            }
        ],
        "steps": [
            {
                "number": 1,
                "instruction": "播放",
                "mandatory": True,
                "audio_path": "audio/01.wav",
                "actions": [
                    {
                        "action_id": "step-001-a01",
                        "type": "control",
                        "text": "播放",
                        "mandatory": True,
                        "target": None,
                    }
                ],
            }
        ],
        "click_targets": [],
    }


def query_set() -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "query_set_id": QUERY_SET_ID,
        "book_id": BOOK_ID,
        "name": "命题组脚本",
        "language": "mixed",
        "source": "official_script",
        "items": [
            {
                "query_id": "zh-99-q001",
                "number": 1,
                "instruction": "播放",
                "audio_path": "audio/01.wav",
                "mandatory": True,
                "lang": "zh",
                "actions": [
                    {
                        "action_id": "zh-99-q001-a01",
                        "kind": "control",
                        "text": "播放",
                        "mandatory": True,
                        "control_action": "play",
                        "seek_query": None,
                        "search_text": None,
                        "highlight_text": None,
                        "target": None,
                        "expected": None,
                    }
                ],
                "expected": None,
            }
        ],
    }


def write_package(root: Path, package: dict[str, Any] | None = None) -> Path:
    """在 root 下写出一个可被读取的 v2 单书包。"""
    package_root = root / BOOK_ID
    (package_root / "pages").mkdir(parents=True, exist_ok=True)
    (package_root / "source").mkdir(parents=True, exist_ok=True)
    (package_root / "audio").mkdir(parents=True, exist_ok=True)
    (package_root / "query_sets").mkdir(parents=True, exist_ok=True)
    (package_root / "pages" / "001.png").write_bytes(b"not inspected by validation")
    (package_root / "source" / "book.pdf").write_bytes(b"pdf")
    (package_root / "audio" / "01.wav").write_bytes(b"not inspected by validation")
    (package_root / "book.json").write_text(
        json.dumps(package or valid_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    (package_root / "query_sets" / f"{QUERY_SET_ID}.json").write_text(
        json.dumps(query_set(), ensure_ascii=False),
        encoding="utf-8",
    )
    return package_root
