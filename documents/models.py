import os
import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from onboarding.models import OnboardingCase, ChecklistItem

User = get_user_model()

# Private storage instance not accessible via public web URL
private_storage = FileSystemStorage(
    location=settings.PRIVATE_STORAGE_ROOT,
    base_url=None  # No public URL
)

def document_upload_path(instance, filename):
    clean_filename = os.path.basename(filename)
    return os.path.join('documents', str(instance.case.id), f"{uuid.uuid4().hex[:8]}_{clean_filename}")

class DocumentStatus(models.TextChoices):
    UPLOADED = 'uploaded', 'Uploaded'
    PROCESSING = 'processing', 'Processing / Extracting'
    PROCESSED = 'processed', 'Processed (Automated)'
    REVIEW_REQUIRED = 'review_required', 'Needs Human Review'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(OnboardingCase, on_delete=models.CASCADE, related_name='documents')
    checklist_item = models.ForeignKey(ChecklistItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    
    file = models.FileField(storage=private_storage, upload_to=document_upload_path)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100, blank=True)
    file_size_bytes = models.BigIntegerField(default=0)
    
    document_type_hint = models.CharField(
        max_length=50,
        default='general',
        help_text="Hint for extraction schema, e.g. tax_form, w9, id, bank_details, certificate"
    )
    status = models.CharField(
        max_length=30,
        choices=DocumentStatus.choices,
        default=DocumentStatus.UPLOADED,
        db_index=True
    )
    
    raw_extracted_text = models.TextField(blank=True)
    extracted_data = models.JSONField(default=dict, blank=True)
    confidence_score = models.FloatField(default=0.0)
    validation_flags = models.JSONField(default=list, blank=True, help_text="List of warnings or missing fields")
    
    is_approved = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_documents')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.file_name} ({self.get_status_display()}) - {self.case.client.company_name}"
