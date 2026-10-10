import os
import sys
import time
import uuid
import signal
import logging
import inspect
import traceback
from datetime import timedelta
from typing import Optional, Any, Tuple
from django.utils import timezone
from django.conf import settings
from django.db import models, OperationalError

from .models import Job, JobStatus
from .registry import registry

logger = logging.getLogger('workflow_engine.worker')

class JobWorker:
    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: Optional[float] = None,
        batch_size: Optional[int] = None,
        lease_duration_seconds: Optional[int] = None,
        base_backoff_seconds: Optional[float] = None,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}-pid{os.getpid()}"
        self.poll_interval = poll_interval or getattr(settings, 'WORKER_POLL_INTERVAL', 1.5)
        self.batch_size = batch_size or getattr(settings, 'WORKER_BATCH_SIZE', 10)
        self.lease_duration = lease_duration_seconds or getattr(settings, 'WORKER_LEASE_DURATION_SECONDS', 60)
        self.base_backoff = base_backoff_seconds or getattr(settings, 'WORKER_BASE_BACKOFF_SECONDS', 5.0)
        self.shutdown_requested = False
        self._current_job: Optional[Job] = None

    def setup_signal_handlers(self):
        """Set up graceful shutdown signal handlers."""
        def handle_signal(signum, frame):
            logger.info("Signal %s received by %s. Initiating graceful shutdown...", signum, self.worker_id)
            self.shutdown_requested = True

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def recover_abandoned_jobs(self) -> int:
        """
        Recovers jobs where status is RUNNING but lease_expires_at is past.
        Prevents abandoned jobs from remaining stuck in running state forever.
        """
        now = timezone.now()
        expired_jobs = Job.objects.filter(
            status=JobStatus.RUNNING,
            lease_expires_at__lte=now
        )
        recovered_count = 0
        for job in expired_jobs:
            if job.attempts >= job.max_attempts:
                # Mark as failed
                rows = Job.objects.filter(id=job.id, lease_token=job.lease_token).update(
                    status=JobStatus.FAILED,
                    completed_at=now,
                    last_error=f"Lease expired (worker {job.worker_id} crashed or abandoned job). Max attempts reached ({job.attempts}/{job.max_attempts}).",
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            else:
                delay = self.base_backoff * (2 ** max(0, job.attempts - 1))
                next_run = now + timedelta(seconds=delay)
                rows = Job.objects.filter(id=job.id, lease_token=job.lease_token).update(
                    status=JobStatus.RETRYING,
                    scheduled_at=next_run,
                    last_error=f"Lease expired (worker {job.worker_id} did not complete within lease window). Requeued for retry.",
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            if rows > 0:
                recovered_count += 1
                logger.warning("Recovered abandoned job %s (type=%s)", job.id, job.job_type)
        return recovered_count

    def claim_next_job(self) -> Optional[Tuple[Job, uuid.UUID]]:
        """
        Discovers due jobs and claims one safely using atomic conditional updates.
        Returns a tuple of (claimed_job, lease_token) or None.
        """
        now = timezone.now()
        # Find candidates
        try:
            candidates = list(Job.objects.filter(
                status__in=[JobStatus.PENDING, JobStatus.RETRYING],
                scheduled_at__lte=now
            ).order_by('priority', 'scheduled_at', 'created_at')[:self.batch_size])
        except OperationalError as exc:
            logger.warning("Database busy or error during job discovery: %s", exc)
            return None

        for candidate in candidates:
            new_lease_token = uuid.uuid4()
            lease_expiry = now + timedelta(seconds=self.lease_duration)
            
            # Atomic conditional update claiming the job
            rows_updated = Job.objects.filter(
                id=candidate.id,
                status=candidate.status,
                lease_token=candidate.lease_token
            ).update(
                status=JobStatus.RUNNING,
                worker_id=self.worker_id,
                lease_token=new_lease_token,
                lease_expires_at=lease_expiry,
                started_at=now,
                attempts=models.F('attempts') + 1,
                updated_at=now,
            )

            if rows_updated == 1:
                candidate.refresh_from_db()
                return candidate, new_lease_token

        return None

    def execute_job(self, job: Job, lease_token: uuid.UUID) -> bool:
        """
        Executes the registered handler for the claimed job.
        Ensures execution occurs outside any open DB transactions and catches all errors.
        """
        self._current_job = job
        logger.info("Worker %s executing job %s (type=%s, attempt=%s/%s)", self.worker_id, job.id, job.job_type, job.attempts, job.max_attempts)
        
        handler = registry.get_handler(job.job_type)
        if not handler:
            err_msg = f"No registered handler found for job type: '{job.job_type}'"
            logger.error(err_msg)
            self._handle_unregistered_failure(job, lease_token, err_msg)
            self._current_job = None
            return False

        try:
            # Check handler signature
            sig = inspect.signature(handler)
            params = sig.parameters
            if 'job' in params:
                result = handler(job.payload, job=job)
            else:
                result = handler(job.payload)
            
            self._finish_success(job, lease_token, result)
            self._current_job = None
            return True
        except Exception as exc:
            logger.exception("Job %s failed with error: %s", job.id, exc)
            self._handle_failure(job, lease_token, exc)
            self._current_job = None
            return False

    def _finish_success(self, job: Job, lease_token: uuid.UUID, result: Any):
        """
        Atomically updates the job as SUCCEEDED if this worker still holds the valid lease.
        """
        now = timezone.now()
        result_dict = result if isinstance(result, dict) else {"result": result}
        
        updated = Job.objects.filter(
            id=job.id,
            lease_token=lease_token
        ).update(
            status=JobStatus.SUCCEEDED,
            completed_at=now,
            result=result_dict,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )
        if updated == 0:
            logger.warning("Stale lease for job %s! Worker %s execution result ignored as lease was lost.", job.id, self.worker_id)
        else:
            logger.info("Job %s completed successfully by worker %s", job.id, self.worker_id)

    def _handle_unregistered_failure(self, job: Job, lease_token: uuid.UUID, error_msg: str):
        now = timezone.now()
        Job.objects.filter(
            id=job.id,
            lease_token=lease_token
        ).update(
            status=JobStatus.FAILED,
            completed_at=now,
            last_error=error_msg,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )

    def _handle_failure(self, job: Job, lease_token: uuid.UUID, exc: Exception):
        now = timezone.now()
        err_msg = f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        
        # Determine if we should retry or fail
        if job.attempts >= job.max_attempts:
            updated = Job.objects.filter(
                id=job.id,
                lease_token=lease_token
            ).update(
                status=JobStatus.FAILED,
                completed_at=now,
                last_error=err_msg,
                lease_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
            if updated > 0:
                logger.error("Job %s exhausted all %s attempts and marked as FAILED.", job.id, job.max_attempts)
        else:
            delay = self.base_backoff * (2 ** max(0, job.attempts - 1))
            next_run = now + timedelta(seconds=delay)
            updated = Job.objects.filter(
                id=job.id,
                lease_token=lease_token
            ).update(
                status=JobStatus.RETRYING,
                scheduled_at=next_run,
                last_error=err_msg,
                lease_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
            if updated > 0:
                logger.info("Job %s scheduled for retry in %.1f seconds (attempt %s/%s)", job.id, delay, job.attempts, job.max_attempts)

    def run(self, max_jobs: Optional[int] = None, once: bool = False):
        """
        Main worker loop. Runs until shutdown requested or max_jobs reached.
        """
        self.setup_signal_handlers()
        logger.info("Starting worker %s (poll_interval=%.2fs, lease_duration=%ss)", self.worker_id, self.poll_interval, self.lease_duration)
        
        jobs_processed = 0
        while not self.shutdown_requested:
            # 1. Recover abandoned jobs periodically
            try:
                self.recover_abandoned_jobs()
            except Exception as exc:
                logger.warning("Error recovering abandoned jobs: %s", exc)

            # 2. Claim and execute one job
            claimed = self.claim_next_job()
            if claimed:
                job, token = claimed
                self.execute_job(job, token)
                jobs_processed += 1
                if max_jobs and jobs_processed >= max_jobs:
                    logger.info("Reached max jobs limit (%s). Exiting worker.", max_jobs)
                    break
                # If there are potentially more jobs, don't sleep
                continue
            
            if once:
                logger.info("Worker ran with --once and no more due jobs found.")
                break

            # 3. Sleep for poll interval
            time.sleep(self.poll_interval)

        logger.info("Worker %s shut down gracefully. Processed %s jobs.", self.worker_id, jobs_processed)
