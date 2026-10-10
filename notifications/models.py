import uuid
from django.db import models
from django.contrib.auth import get_user_model
from onboarding.models import OnboardingCase

User = get_user_model()

class NotificationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    SENT = 'sent', 'Sent'
    FAILED = 'failed', 'Failed'


class EmailNotification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_email = models.EmailField()
    recipient_name = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    template_name = models.CharField(max_length=100, blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, unique=True, db_index=True)
    correlation_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Email to {self.recipient_email}: '{self.subject}' [{self.status}]"


class StaffAlert(models.Model):
    class AlertType(models.TextChoices):
        INFO = 'info', 'Information'
        ACTION_REQUIRED = 'action_required', 'Action Required'
        WARNING = 'warning', 'Warning / Overdue'
        ERROR = 'error', 'Error / Failure'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='staff_alerts')
    case = models.ForeignKey(OnboardingCase, on_delete=models.CASCADE, null=True, blank=True, related_name='staff_alerts')
    
    title = models.CharField(max_length=255)
    message = models.TextField()
    alert_type = models.CharField(max_length=20, choices=AlertType.choices, default=AlertType.INFO)
    is_read = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Alert: {self.title} ({self.get_alert_type_display()})"
