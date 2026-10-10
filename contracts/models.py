import uuid
from django.db import models
from clients.models import Client

class ContractStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    SENT = 'sent', 'Sent for Signature'
    SIGNED = 'signed', 'Signed'
    CANCELLED = 'cancelled', 'Cancelled'


class Contract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='contracts')
    title = models.CharField(max_length=255, default="Master Services Agreement")
    contract_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default='USD')
    status = models.CharField(
        max_length=20,
        choices=ContractStatus.choices,
        default=ContractStatus.DRAFT,
        db_index=True
    )
    terms_summary = models.TextField(blank=True)
    
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by_name = models.CharField(max_length=255, blank=True)
    signed_by_email = models.CharField(max_length=255, blank=True)
    signature_reference = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.client.company_name} ({self.get_status_display()})"
