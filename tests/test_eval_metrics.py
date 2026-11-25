"""Evaluation summaries: per-kind latency, routing accuracy and run delta."""

from __future__ import annotations

import unittest

from contracts.models import EvalResult, InteractionKind
from pipeline.eval import _delta_metrics, summarize


def result(
    case_id: str,
    kind: InteractionKind,
    verdict: str,
    latency_ms: int,
    served_kind: InteractionKind | None = None,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        kind=kind,
        served_kind=served_kind,
        status="ok",
        verdict=verdict,
        latency_ms=latency_ms,
    )


class SummarizeTests(unittest.TestCase):
    def test_latency_and_routing_are_reported_per_kind(self) -> None:
        results = [
            result("q1", InteractionKind.qa, "ok", 100, InteractionKind.qa),
            result("q2", InteractionKind.qa, "fallback", 300, InteractionKind.qa),
            result("c1", InteractionKind.control, "ok", 10, InteractionKind.control),
            result("s1", InteractionKind.seek, "ok", 50, InteractionKind.qa),
        ]

        metrics = summarize(results, [])

        self.assertEqual(10, metrics["latency_by_kind"]["control"]["p50_ms"])
        self.assertEqual(100, metrics["latency_by_kind"]["qa"]["p50_ms"])
        self.assertEqual(300, metrics["latency_by_kind"]["qa"]["p95_ms"])
        self.assertEqual(2, metrics["latency_by_kind"]["qa"]["count"])
        self.assertEqual(3, metrics["classification_ok"])
        self.assertEqual(4, metrics["classification_total"])
        self.assertEqual(0.75, metrics["classification_accuracy"])
        self.assertEqual(1, metrics["by_kind_detail"]["qa"]["fallback"])

    def test_delta_compares_counts_and_latency(self) -> None:
        current = summarize(
            [
                result("q1", InteractionKind.qa, "ok", 100, InteractionKind.qa),
                result("c1", InteractionKind.control, "ok", 10, InteractionKind.control),
            ],
            [],
        )
        previous = summarize(
            [
                result("q1", InteractionKind.qa, "fallback", 200, InteractionKind.qa),
                result("c1", InteractionKind.control, "ok", 20, InteractionKind.control),
                result("s1", InteractionKind.seek, "ok", 60, InteractionKind.seek),
            ],
            [],
        )

        delta = _delta_metrics(current, previous, "run-old")

        self.assertEqual("run-old", delta["previous_run_id"])
        self.assertEqual(0, delta["ok"])
        self.assertEqual(-1, delta["total"])
        self.assertEqual(1, delta["by_kind"]["qa"]["ok"])
        self.assertEqual(-1, delta["by_kind"]["seek"]["total"])
        self.assertLess(delta["p95_ms"], 0)


if __name__ == "__main__":
    unittest.main()
