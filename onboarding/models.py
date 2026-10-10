import uuid
import secrets
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from clients.models import Client
from contracts.models import Contract

User = get_user_model()

class OnboardingStatus(models.TextChoices):
    NOT_STARTED = 'not_started', 'Not Started'
    IN_PROGRESS = 'in_progress', 'In Progress'
    AWAITING_REVIEW = 'awaiting_review', 'Awaiting Staff Review'
    COMPLETED = 'completed', 'Completed'
    STALLED = 'stalled', 'Stalled / Overdue'
    CANCELLED = 'cancelled', 'Cancelled'


class ChecklistCategory(models.TextChoices):
    INTAKE_FORM = 'intake_form', 'Intake Form'
    DOCUMENT_UPLOAD = 'document_upload', 'Document Upload'
    CRM_SETUP = 'crm_setup', 'CRM Record Creation'
    FOLDER_SETUP = 'folder_setup', 'Client Folder Creation'
    PROJECT_SETUP = 'project_setup', 'Project Tasks Setup'
    MANUAL_REVIEW = 'manual_review', 'Staff Review & Approval'


def generate_access_token():
    return secrets.token_urlsafe(32)


class OnboardingCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='onboarding_cases')
    contract = models.OneToOneField(Contract, on_delete=models.CASCADE, related_name='onboarding_case')
    
    status = models.CharField(
        max_length=30,
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.NOT_STARTED,
        db_index=True
    )
    assigned_staff = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_onboarding_cases'
    )
    client_access_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_access_token,
        db_index=True,
        help_text="Secure token for client portal intake"
    )
    
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    target_completion_date = models.DateField(null=True, blank=True)
    
    # External Integration References
    folder_id = models.CharField(max_length=255, blank=True, null=True)
    folder_url = models.CharField(max_length=500, blank=True, null=True)
    crm_id = models.CharField(max_length=255, blank=True, null=True)
    crm_url = models.CharField(max_length=500, blank=True, null=True)
    project_board_id = models.CharField(max_length=255, blank=True, null=True)
    project_board_url = models.CharField(max_length=500, blank=True, null=True)
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Case: {self.client.company_name} ({self.get_status_display()})"

    @property
    def progress_percentage(self) -> int:
        total = self.checklist_items.count()
        if total == 0:
            return 0
        completed = self.checklist_items.filter(is_completed=True).count()
        return int((completed / total) * 100)

    @property
    def is_all_required_items_completed(self) -> bool:
        required_items = self.checklist_items.filter(is_required=True)
        if not required_items.exists():
            return False
        return not required_items.filter(is_completed=False).exists()


class ChecklistItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(OnboardingCase, on_delete=models.CASCADE, related_name='checklist_items')
    category = models.CharField(max_length=30, choices=ChecklistCategory.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    due_date = models.DateField(null=True, blank=True)
    reminder_count = models.IntegerField(default=0)
    max_reminders = models.IntegerField(default=3)
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    order = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at']

    def __str__(self):
        status = "Done" if self.is_completed else "Pending"
        return f"[{status}] {self.title} - {self.case.client.company_name}"

    def mark_completed(self, user=None):
        self.is_completed = True
        self.completed_at = timezone.now()
        if user and user.is_authenticated:
            self.completed_by = user
        self.save(update_fields=['is_completed', 'completed_at', 'completed_by', 'updated_at'])


class ClientIntakeSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.OneToOneField(OnboardingCase, on_delete=models.CASCADE, related_name='intake_submission')
    submitted_at = models.DateTimeField(default=timezone.now)
    
    company_legal_name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=100, blank=True)
    billing_contact_name = models.CharField(max_length=255)
    billing_contact_email = models.EmailField()
    billing_address = models.TextField()
    
    primary_use_case = models.TextField(blank=True)
    target_launch_date = models.DateField(null=True, blank=True)
    technical_contact_name = models.CharField(max_length=255, blank=True)
    technical_contact_email = models.EmailField(blank=True)
    privacy_consent_given = models.BooleanField(default=False)
    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Intake Submission: {self.company_legal_name} ({self.case.id})"
