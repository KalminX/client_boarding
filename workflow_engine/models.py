import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings

class JobStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    RETRYING = 'retrying', 'Retrying'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.PENDING,
        db_index=True
    )
    priority = models.IntegerField(default=100, db_index=True, help_text="Lower value means higher priority")
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    worker_id = models.CharField(max_length=128, null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True, db_index=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    
    last_error = models.TextField(blank=True, default='')
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, unique=True, db_index=True)
    correlation_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['priority', 'scheduled_at', 'created_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_at', 'priority']),
            models.Index(fields=['status', 'lease_expires_at']),
        ]

    def __str__(self):
        return f"Job {self.job_type} ({self.id}) - {self.status} (attempt {self.attempts}/{self.max_attempts})"

    @property
    def is_terminal(self):
        return self.status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED]

    @property
    def is_running(self):
        return self.status == JobStatus.RUNNING
