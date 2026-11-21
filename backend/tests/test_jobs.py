import tempfile
import unittest
from pathlib import Path

from backend.app.jobs import JobManager, JobStore


class SuccessfulRunner:
    def run(self, book_id: str, report) -> None:
        self.book_id = book_id
        report("scene", 0.4)
        report("video", 0.8)


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
        self.assertEqual("completed", job.status)
        self.assertEqual("index", job.stage)
        self.assertEqual(1.0, job.progress)
        self.assertEqual(job.job_id, self.store.get(job.job_id).job_id)

    def test_records_readable_failure(self) -> None:
        manager = JobManager(self.store, FailingRunner())
        job = manager.submit("zh-01", background=False)
        self.assertEqual("failed", job.status)
        self.assertEqual("video provider timed out", job.error)

    def test_default_runner_fails_explicitly(self) -> None:
        manager = JobManager(self.store)
        job = manager.submit("zh-01", background=False)
        self.assertEqual("failed", job.status)
        self.assertIn("not configured", job.error)
