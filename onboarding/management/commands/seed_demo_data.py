import os
from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.base import ContentFile

from clients.models import Client
from contracts.models import Contract, ContractStatus
from onboarding.models import OnboardingCase, ChecklistItem, OnboardingStatus, ChecklistCategory, ClientIntakeSubmission
from onboarding.services import initialize_onboarding_for_signed_contract
from documents.models import Document, DocumentStatus
from workflow_engine.worker import JobWorker
from workflow_engine.dispatcher import enqueue_job

User = get_user_model()

class Command(BaseCommand):
    help = "Seeds realistic demo clients, contracts, onboarding cases, and executions."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding demonstration data..."))

        # 1. Create or get admin user
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@boardflow.demo",
                "is_staff": True,
                "is_superuser": True,
            }
        )
        if created:
            admin_user.set_password("admin123")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created staff user 'admin' (password: admin123)"))

        # 2. Client 1: Meridian Health Tech (Signed, In Progress, Automated Jobs processed)
        c1, _ = Client.objects.get_or_create(
            primary_email="elena.rostova@meridianhealth.io",
            defaults={
                "name": "Dr. Elena Rostova",
                "company_name": "Meridian Health Tech LLC",
                "phone": "+1 (415) 889-0123",
                "billing_address": "500 Howard Street, Suite 800, San Francisco, CA 94105",
                "website": "https://meridianhealth.io",
                "industry": "Healthcare & Life Sciences",
            }
        )

        contract1, _ = Contract.objects.get_or_create(
            client=c1,
            title="Enterprise Cloud Healthcare MSA",
            defaults={
                "contract_value": Decimal("48000.00"),
                "currency": "USD",
                "status": ContractStatus.DRAFT,
                "terms_summary": "HIPAA compliant cloud provisioning, 24/7 dedicated support, onboarding data migration.",
            }
        )

        case1, newly_created = initialize_onboarding_for_signed_contract(
            contract=contract1,
            signed_by_name=c1.name,
            signed_by_email=c1.primary_email,
            staff_user=admin_user
        )

        # Submit intake form for Client 1
        if not hasattr(case1, 'intake_submission'):
            ClientIntakeSubmission.objects.create(
                case=case1,
                company_legal_name=c1.company_name,
                tax_id="94-3829104",
                billing_contact_name=c1.name,
                billing_contact_email=c1.primary_email,
                billing_address=c1.billing_address,
                primary_use_case="Integration with EHR system and real-time patient analytics telemetry.",
                target_launch_date=(timezone.now() + timedelta(days=10)).date(),
                technical_contact_name="Marcus Vance",
                technical_contact_email="marcus@meridianhealth.io",
                privacy_consent_given=True,
            )
            intake_item = case1.checklist_items.filter(category=ChecklistCategory.INTAKE_FORM).first()
            if intake_item:
                intake_item.mark_completed(user=admin_user)

        # Upload a sample W9 document for Client 1
        sample_w9_content = b"""
FORM W-9 (Rev. March 2024) - Department of the Treasury Internal Revenue Service
1. Legal Name of Entity: Meridian Health Tech LLC
2. Business Name: Meridian Health Tech
3. Federal Tax Classification: Limited Liability Company (Corporation)
4. Address: 500 Howard Street, Suite 800, San Francisco, CA 94105
Part I - Taxpayer Identification Number (TIN):
EIN: 94-3829104
Part II - Certification:
Under penalties of perjury, I certify that the number shown on this form is my correct TIN.
Authorized Signatory: Dr. Elena Rostova
Date: 2026-03-15
"""
        doc1, doc1_created = Document.objects.get_or_create(
            case=case1,
            file_name="Meridian_Health_W9_Signed.pdf",
            defaults={
                "document_type_hint": "tax_form",
                "status": DocumentStatus.PROCESSED,
                "confidence_score": 0.96,
                "raw_extracted_text": sample_w9_content.decode('utf-8'),
                "extracted_data": {
                    "entity_name": "Meridian Health Tech LLC",
                    "tax_id": "94-3829104",
                    "address": "500 Howard Street, Suite 800, San Francisco, CA 94105",
                    "authorized_signatory": "Dr. Elena Rostova",
                    "date_identified": "2026-03-15"
                },
                "validation_flags": [],
                "file_size_bytes": len(sample_w9_content),
                "is_approved": True,
                "reviewed_by": admin_user,
                "reviewed_at": timezone.now(),
                "review_notes": "Verified against IRS database.",
            }
        )
        if doc1_created:
            doc1.file.save("Meridian_Health_W9_Signed.pdf", ContentFile(sample_w9_content))
            tax_item = case1.checklist_items.filter(category=ChecklistCategory.DOCUMENT_UPLOAD, title__icontains='tax').first()
            if tax_item:
                tax_item.mark_completed(user=admin_user)

        # 3. Client 2: Vanguard Robotics (Awaiting review with a flagged document)
        c2, _ = Client.objects.get_or_create(
            primary_email="claire@vanguardrobotics.com",
            defaults={
                "name": "Claire Zhang",
                "company_name": "Vanguard Robotics Inc",
                "phone": "+1 (617) 555-9012",
                "billing_address": "77 Massachusetts Ave, Cambridge, MA 02139",
                "website": "https://vanguardrobotics.com",
                "industry": "Autonomous Systems",
            }
        )
        contract2, _ = Contract.objects.get_or_create(
            client=c2,
            title="Custom Hardware & AI Pipeline SLA",
            defaults={
                "contract_value": Decimal("115000.00"),
                "status": ContractStatus.DRAFT,
            }
        )
        case2, _ = initialize_onboarding_for_signed_contract(
            contract=contract2,
            signed_by_name=c2.name,
            signed_by_email=c2.primary_email,
            staff_user=admin_user
        )

        sample_flagged_content = b"""
CERTIFICATE OF FORMATION
Name: Vanguard Robotics Inc
Address: Cambridge MA
(Missing Federal Tax ID)
Signatory: Claire Zhang
"""
        doc2, doc2_created = Document.objects.get_or_create(
            case=case2,
            file_name="Vanguard_Incorporation_Scan.pdf",
            defaults={
                "document_type_hint": "incorporation",
                "status": DocumentStatus.REVIEW_REQUIRED,
                "confidence_score": 0.65,
                "raw_extracted_text": sample_flagged_content.decode('utf-8'),
                "extracted_data": {
                    "entity_name": "Vanguard Robotics Inc",
                    "address": "Cambridge MA",
                    "authorized_signatory": "Claire Zhang"
                },
                "validation_flags": ["Missing Tax Identification Number (EIN/SSN)"],
                "file_size_bytes": len(sample_flagged_content),
                "is_approved": False,
            }
        )
        if doc2_created:
            doc2.file.save("Vanguard_Incorporation_Scan.pdf", ContentFile(sample_flagged_content))

        # 4. Client 3: Apex Logistics (Unsigned Draft Contract - Ready to test interactive Sign Contract flow)
        c3, _ = Client.objects.get_or_create(
            primary_email="jordan.reed@apexlogistics.com",
            defaults={
                "name": "Jordan Reed",
                "company_name": "Apex Global Logistics LLC",
                "phone": "+1 (312) 440-1928",
                "billing_address": "200 South Michigan Ave, Chicago, IL 60604",
                "website": "https://apexlogistics.com",
                "industry": "Supply Chain & Freight",
            }
        )
        Contract.objects.get_or_create(
            client=c3,
            title="Master Logistics Software Agreement 2026",
            defaults={
                "contract_value": Decimal("35000.00"),
                "status": ContractStatus.SENT,
                "terms_summary": "Full freight management module integration with real-time GPS tracking.",
            }
        )

        # Process any pending jobs from seeding
        worker = JobWorker(poll_interval=0.1)
        worker.run(once=True)

        self.stdout.write(self.style.SUCCESS("Successfully seeded demo data!"))
        self.stdout.write("Credentials: Username 'admin', Password 'admin123'")
        self.stdout.write("Demo accounts created: Meridian Health Tech (Active), Vanguard Robotics (Needs Review), Apex Logistics (Ready to Sign)")
