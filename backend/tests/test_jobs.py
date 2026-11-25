import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.app.jobs import JobManager, JobStore
from backend.app.models import JobStage, JobStatus


class SuccessfulRunner:
    def run(self, book_id: str, report) -> None:
        self.book_id = book_id
        report("scene", 0.4)
        report("video", 0.8)


class DegradedRunner:
    def run(self, book_id: str, report):
        report("compose", 1.0)
        return SimpleNamespace(
            status="degraded",
            manifest_path="derived/manifest.json",
        )


class FailingRunner:
    def run(self, book_id: str, report) -> None:
        report("video", 0.5)
        raise RuntimeError("video provider timed out")


class JobManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temporary.name) / "jobs.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_completes_job_and_persists_progress(self) -> None:
        manager = JobManager(self.store, SuccessfulRunner())
        job = manager.submit("zh-01", background=False)
        self.assertEqual(JobStatus.completed, job.status)
        self.assertEqual(JobStage.index, job.stage)
        self.assertEqual(1.0, job.progress)
        self.assertEqual(job.job_id, self.store.get(job.job_id).job_id)

    def test_records_readable_failure(self) -> None:
        manager = JobManager(self.store, FailingRunner())
        job = manager.submit("zh-01", background=False)
        self.assertEqual(JobStatus.failed, job.status)
        self.assertEqual("video provider timed out", job.error)

    def test_degraded_runner_sets_status_and_manifest_path(self) -> None:
        manager = JobManager(self.store, DegradedRunner())
        job = manager.submit("zh-01", background=False)
        self.assertEqual(JobStatus.degraded, job.status)
        self.assertTrue(job.degraded)
        self.assertEqual("derived/manifest.json", job.manifest_path)

    def test_failure_carries_stage_error_code(self) -> None:
        manager = JobManager(self.store, FailingRunner())
        job = manager.submit("zh-01", background=False)
        self.assertEqual("VIDEO_FAILED", job.error_code)
        self.assertTrue(job.retryable)
        self.assertFalse(job.degraded)

    def test_default_runner_fails_explicitly(self) -> None:
        manager = JobManager(self.store)
        job = manager.submit("zh-01", background=False)
        self.assertEqual(JobStatus.failed, job.status)
        self.assertIn("not configured", job.error)
        self.assertEqual("STORY_FAILED", job.error_code)

    def test_job_payload_is_v2_shape(self) -> None:
        manager = JobManager(self.store, SuccessfulRunner())
        job = manager.submit("zh-01", background=False)
        payload = job.model_dump(mode="json")
        for field in (
            "job_id",
            "book_id",
            "status",
            "stage",
            "progress",
            "created_at",
            "updated_at",
            "error",
            "error_code",
            "degraded",
            "retryable",
            "manifest_path",
        ):
            self.assertIn(field, payload)


if __name__ == "__main__":
    unittest.main()
