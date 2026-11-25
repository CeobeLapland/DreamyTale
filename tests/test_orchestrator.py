"""Orchestrator tests with fake stages (no models, no real books)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import orchestrator
from pipeline.config import BookSpec
from pipeline.orchestrator import (
    OrchestrationError,
    Stage,
    StageOutcome,
    run_book,
    select_stages,
)


class StageSelectionTests(unittest.TestCase):
    def test_run_tail(self) -> None:
        names = [stage.name for stage in select_stages("index", "compose")]
        self.assertEqual(["index", "knowledge", "hotspots", "video", "compose"], names)

    def test_critic_runs_after_compose(self) -> None:
        names = [stage.name for stage in select_stages("compose")]
        self.assertEqual(["compose", "critic"], names)

    def test_unknown_stage_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_stages("nope", "compose")

    def test_from_must_come_before_to(self) -> None:
        with self.assertRaises(ValueError):
            select_stages("compose", "index")


class OrchestratorCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.data = root / "data" / "books"
        (self.data / "zh-99").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "config" / "models.yaml").write_text("ocr: {}\n", encoding="utf-8")
        self.spec = BookSpec("zh-99", "", "", "", "zh-CN", "narrative", "test")

        def first(spec: BookSpec) -> StageOutcome:
            path = orchestrator.DATA / spec.book_id / "out" / "one.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("one", encoding="utf-8")
            return StageOutcome(
                outputs=["out/one.txt"], provider="fake", model="fake-one"
            )

        def second(spec: BookSpec) -> StageOutcome:
            path = orchestrator.DATA / spec.book_id / "out" / "two.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("two", encoding="utf-8")
            return StageOutcome(
                outputs=["out/two.txt"], provider="fake", model="fake-two"
            )

        self.stages = (
            Stage("one", "AgentA", "ingest", (), first, ("out/one.txt",)),
            Stage("two", "AgentB", "index", ("one",), second, ("out/two.txt",)),
        )
        self.patchers = [
            mock.patch.object(orchestrator, "DATA", self.data),
            mock.patch.object(orchestrator, "ROOT", root),
            mock.patch.object(orchestrator, "TRACE_ROOT", root / "data" / "traces"),
            mock.patch.object(orchestrator, "STAGES", self.stages),
            mock.patch.object(
                orchestrator,
                "STAGES_BY_NAME",
                {stage.name: stage for stage in self.stages},
            ),
            mock.patch.object(orchestrator, "STAGE_ORDER", ["one", "two"]),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def test_runs_all_stages_then_hits_cache(self) -> None:
        first = run_book(self.spec)
        self.assertEqual("completed", first.status)
        self.assertTrue(Path(first.manifest_path).is_file())
        self.assertTrue(Path(first.trace_path).is_file())

        manifest = json.loads(Path(first.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(["one", "two"], [item["name"] for item in manifest["stages"]])
        self.assertEqual(["out/one.txt", "out/two.txt"], [
            item["path"] for item in manifest["artifacts"]
        ])

        second = run_book(self.spec)
        self.assertEqual(2, second.cached)
        self.assertEqual(0, second.degraded)

    def test_required_failure_writes_a_failed_manifest(self) -> None:
        def broken(_spec: BookSpec) -> StageOutcome:
            raise RuntimeError("boom")

        broken_stages = (
            Stage("one", "AgentA", "ingest", (), broken, ("out/one.txt",)),
        )
        with (
            mock.patch.object(orchestrator, "STAGES", broken_stages),
            mock.patch.object(
                orchestrator,
                "STAGES_BY_NAME",
                {"one": broken_stages[0]},
            ),
            mock.patch.object(orchestrator, "STAGE_ORDER", ["one"]),
        ):
            with self.assertRaises(OrchestrationError) as caught:
                run_book(self.spec)

        report = caught.exception.report
        self.assertEqual("failed", report.status)
        self.assertEqual("one", report.failed)
        manifest = json.loads(Path(report.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual("failed", manifest["status"])
        self.assertEqual("failed", manifest["stages"][0]["status"])


class ManualInputHashTests(unittest.TestCase):
    def test_manual_edit_changes_the_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data" / "books"
            book = data / "zh-99"
            (book / "manual").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "config" / "models.yaml").write_text("ocr: {}\n", encoding="utf-8")
            spec = BookSpec("zh-99", "", "", "", "zh-CN", "narrative", "test")
            narrative = book / "manual" / "narrative.json"

            with (
                mock.patch.object(orchestrator, "DATA", data),
                mock.patch.object(orchestrator, "ROOT", root),
            ):
                narrative.write_text('{"pages": {}}', encoding="utf-8")
                before = orchestrator._global_input_hash(spec)
                narrative.write_text('{"pages": {"1": {"text": "human"}}}', encoding="utf-8")
                after = orchestrator._global_input_hash(spec)

        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
