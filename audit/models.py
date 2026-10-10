import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from onboarding.models import OnboardingCase

User = get_user_model()

class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(OnboardingCase, on_delete=models.CASCADE, null=True, blank=True, related_name='audit_events')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    event_type = models.CharField(max_length=100, db_index=True)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        case_info = f" [Case {self.case.id}]" if self.case else ""
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.event_type}{case_info}: {self.description[:50]}"


def record_audit_event(event_type: str, description: str, case=None, user=None, metadata=None, ip_address=None) -> AuditEvent:
    """Convenience helper to record an immutable audit event."""
    return AuditEvent.objects.create(
        event_type=event_type,
        description=description,
        case=case,
        user=user if user and user.is_authenticated else None,
        metadata=metadata or {},
        ip_address=ip_address,
    )
