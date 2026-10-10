import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from workflow_engine.models import Job, JobStatus
from workflow_engine.dispatcher import enqueue_job, retry_job, cancel_job
from workflow_engine.registry import registry
from workflow_engine.worker import JobWorker

class WorkflowEngineJobQueueTests(TestCase):
    def setUp(self):
        # Register a test dummy handler
        @registry.register("test_echo_job")
        def handler_echo(payload):
            return {"echo": payload.get("text", "")}

        @registry.register("test_failing_job")
        def handler_fail(payload):
            raise RuntimeError("Simulated transient error")

    def test_01_job_creation_and_persistence(self):
        """1. Job creation and persistence in database."""
        job = enqueue_job(
            job_type="test_echo_job",
            payload={"text": "hello_world"},
            priority=50,
            correlation_id="case-123"
        )
        self.assertIsNotNone(job.id)
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.priority, 50)
        self.assertEqual(job.correlation_id, "case-123")
        self.assertEqual(job.attempts, 0)

        # Fetch from DB
        fetched = Job.objects.get(id=job.id)
        self.assertEqual(fetched.payload["text"], "hello_world")

    def test_02_idempotent_job_enqueueing(self):
        """2. Prevent duplicate jobs when idempotency_key is supplied."""
        job1 = enqueue_job(
            job_type="test_echo_job",
            payload={"msg": "first"},
            idempotency_key="idemp-key-100"
        )
        job2 = enqueue_job(
            job_type="test_echo_job",
            payload={"msg": "second"},
            idempotency_key="idemp-key-100"
        )
        self.assertEqual(job1.id, job2.id)
        self.assertEqual(Job.objects.filter(idempotency_key="idemp-key-100").count(), 1)

    def test_03_scheduled_jobs_not_running_early(self):
        """3. Scheduled jobs for future execution are not claimed before run_at."""
        future_time = timezone.now() + timedelta(hours=2)
        future_job = enqueue_job(
            job_type="test_echo_job",
            payload={"text": "future"},
            run_at=future_time
        )
        worker = JobWorker(poll_interval=0.1)
        claimed = worker.claim_next_job()
        self.assertIsNone(claimed)
        
        future_job.refresh_from_db()
        self.assertEqual(future_job.status, JobStatus.PENDING)

    def test_04_successful_handler_execution(self):
        """4. Successful handler execution marks job as SUCCEEDED."""
        job = enqueue_job(
            job_type="test_echo_job",
            payload={"text": "compute_result"}
        )
        worker = JobWorker(poll_interval=0.1)
        claimed = worker.claim_next_job()
        self.assertIsNotNone(claimed)
        claimed_job, token = claimed
        
        success = worker.execute_job(claimed_job, token)
        self.assertTrue(success)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.result.get("echo"), "compute_result")
        self.assertIsNotNone(job.completed_at)
        self.assertIsNone(job.lease_token)

    def test_05_transient_failure_and_retry_behavior(self):
        """5. Transient failure triggers retry with exponential backoff."""
        job = enqueue_job(
            job_type="test_failing_job",
            payload={"attempt": 1},
            max_attempts=3
        )
        worker = JobWorker(poll_interval=0.1, base_backoff_seconds=2.0)
        claimed = worker.claim_next_job()
        self.assertIsNotNone(claimed)
        claimed_job, token = claimed
        
        success = worker.execute_job(claimed_job, token)
        self.assertFalse(success)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RETRYING)
        self.assertEqual(job.attempts, 1)
        self.assertIn("Simulated transient error", job.last_error)
        # Scheduled in future
        self.assertGreater(job.scheduled_at, timezone.now() - timedelta(seconds=1))

    def test_06_maximum_attempt_exhaustion(self):
        """6. Max attempt exhaustion transitions job to FAILED."""
        job = enqueue_job(
            job_type="test_failing_job",
            payload={},
            max_attempts=1
        )
        worker = JobWorker(poll_interval=0.1)
        claimed = worker.claim_next_job()
        claimed_job, token = claimed
        
        worker.execute_job(claimed_job, token)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.attempts, 1)
        self.assertIsNotNone(job.completed_at)

        # Manual retry should safely requeue
        requeued = retry_job(job.id)
        self.assertEqual(requeued.status, JobStatus.PENDING)
        self.assertIsNone(requeued.lease_token)

    def test_07_recovery_of_abandoned_jobs(self):
        """7. Recovery of abandoned jobs when worker crashes or lease expires."""
        past_time = timezone.now() - timedelta(seconds=120)
        abandoned_job = Job.objects.create(
            job_type="test_echo_job",
            payload={},
            status=JobStatus.RUNNING,
            worker_id="crashed-worker-99",
            lease_token=uuid.uuid4(),
            lease_expires_at=past_time,
            attempts=1,
            max_attempts=3,
        )
        worker = JobWorker(poll_interval=0.1)
        recovered_count = worker.recover_abandoned_jobs()
        self.assertEqual(recovered_count, 1)

        abandoned_job.refresh_from_db()
        self.assertEqual(abandoned_job.status, JobStatus.RETRYING)
        self.assertIsNone(abandoned_job.lease_token)
        self.assertIn("Lease expired", abandoned_job.last_error)

    def test_08_protection_against_stale_worker_completion(self):
        """8. Protection against stale worker execution overwriting newer job state."""
        worker1 = JobWorker(worker_id="worker-1", lease_duration_seconds=10)
        worker2 = JobWorker(worker_id="worker-2", lease_duration_seconds=60)

        job = enqueue_job(job_type="test_echo_job", payload={"num": 42})
        claimed1 = worker1.claim_next_job()
        job1, token1 = claimed1

        # Simulate worker1 hanging and lease expiring
        Job.objects.filter(id=job.id).update(lease_expires_at=timezone.now() - timedelta(seconds=5))
        worker2.recover_abandoned_jobs()
        # Ensure job is due for worker2
        Job.objects.filter(id=job.id).update(scheduled_at=timezone.now() - timedelta(seconds=1))

        # worker2 claims the job with a new token
        claimed2 = worker2.claim_next_job()
        job2, token2 = claimed2
        self.assertNotEqual(token1, token2)

        # Now worker1 wakes up late and attempts to mark success with stale token1
        worker1._finish_success(job1, token1, {"result": "stale_result"})

        # The job should still be held by worker2 with status RUNNING
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.lease_token, token2)

        # Now worker2 finishes successfully
        worker2._finish_success(job2, token2, {"result": "correct_result"})
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.result.get("result"), "correct_result")
