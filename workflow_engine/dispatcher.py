import logging
from typing import Optional, Dict, Any, Tuple
from django.utils import timezone
from django.conf import settings
from django.db import IntegrityError, transaction
from .models import Job, JobStatus
from .registry import registry

logger = logging.getLogger(__name__)

def enqueue_job(
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
    run_at: Optional[Any] = None,
    idempotency_key: Optional[str] = None,
    priority: int = 100,
    max_attempts: Optional[int] = None,
    correlation_id: Optional[str] = None,
    validate_type: bool = True,
) -> Job:
    """
    Persistently enqueues a job to the database queue.
    Supports immediate or scheduled execution, idempotency keys, and correlation IDs.
    """
    if validate_type and not registry.is_registered(job_type):
        logger.warning(
            "Enqueueing job type '%s' which is not currently registered in the in-memory registry.",
            job_type
        )

    payload = payload or {}
    scheduled_at = run_at or timezone.now()
    if max_attempts is None:
        max_attempts = getattr(settings, 'WORKER_MAX_RETRIES', 3)

    if idempotency_key:
        # Check if job with this idempotency key already exists
        existing = Job.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            logger.info("Job with idempotency key '%s' already exists (id=%s). Returning existing job.", idempotency_key, existing.id)
            return existing

    try:
        job = Job.objects.create(
            job_type=job_type,
            payload=payload,
            status=JobStatus.PENDING,
            priority=priority,
            max_attempts=max_attempts,
            scheduled_at=scheduled_at,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        logger.info("Enqueued job %s (type=%s, scheduled_at=%s, idempotency_key=%s)", job.id, job_type, scheduled_at, idempotency_key)
        return job
    except IntegrityError:
        # Concurrent insert with same idempotency key
        if idempotency_key:
            existing = Job.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
        raise


def retry_job(job_id: Any) -> Optional[Job]:
    """
    Manually retries a failed or cancelled job by resetting its status to pending
    and scheduling it for immediate execution. Preserves previous history.
    """
    with transaction.atomic():
        try:
            job = Job.objects.select_for_update().get(id=job_id)
        except Job.DoesNotExist:
            return None

        job.status = JobStatus.PENDING
        job.scheduled_at = timezone.now()
        job.lease_token = None
        job.lease_expires_at = None
        job.worker_id = None
        job.last_error = f"[Manually requeued at {timezone.now().isoformat()}] Previous error: {job.last_error}"
        job.save()
        logger.info("Manually requeued job %s", job.id)
        return job


def cancel_job(job_id: Any) -> Optional[Job]:
    """Cancels a pending or retrying job."""
    with transaction.atomic():
        try:
            job = Job.objects.select_for_update().get(id=job_id)
        except Job.DoesNotExist:
            return None

        if job.status in [JobStatus.PENDING, JobStatus.RETRYING]:
            job.status = JobStatus.CANCELLED
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'completed_at', 'updated_at'])
            logger.info("Cancelled job %s", job.id)
        return job
