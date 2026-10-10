from decimal import Decimal
from django.test import TestCase, Client as HttpClient
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from clients.models import Client
from contracts.models import Contract
from onboarding.models import OnboardingCase, ChecklistCategory
from onboarding.services import initialize_onboarding_for_signed_contract
from documents.models import Document, DocumentStatus
from workflow_engine.handlers import handle_process_uploaded_document

User = get_user_model()

class DocumentProcessingAndReviewTests(TestCase):
    def setUp(self):
        self.http_client = HttpClient()
        self.staff_user = User.objects.create_user(username="staff1", password="password123", is_staff=True)
        self.client_obj = Client.objects.create(
            name="John Doe",
            company_name="Apex Global",
            primary_email="john@apex.com",
            billing_address="500 Tech Blvd"
        )
        self.contract = Contract.objects.create(
            client=self.client_obj,
            title="Apex MSA",
            contract_value=Decimal("20000.00")
        )
        self.case, _ = initialize_onboarding_for_signed_contract(self.contract, staff_user=self.staff_user)

    def test_12_document_extraction_validation(self):
        """12. Document extraction validation, text parsing, and confidence scoring."""
        file_content = b"""
FORM W-9 (Rev. 2024)
Entity Name: Apex Global LLC
Address: 500 Tech Blvd, Suite 300
Tax ID: 12-9876543
Signatory: John Doe
Date: 2026-04-01
"""
        uploaded = SimpleUploadedFile("w9_apex.pdf", file_content, content_type="application/pdf")
        doc = Document.objects.create(
            case=self.case,
            file=uploaded,
            file_name="w9_apex.pdf",
            document_type_hint="tax_form",
            status=DocumentStatus.UPLOADED,
        )

        res = handle_process_uploaded_document({"document_id": str(doc.id), "case_id": str(self.case.id)})
        doc.refresh_from_db()

        self.assertIn("tax_id", doc.extracted_data)
        self.assertEqual(doc.extracted_data["tax_id"], "12-9876543")
        self.assertGreaterEqual(doc.confidence_score, 0.75)
        self.assertEqual(doc.status, DocumentStatus.PROCESSED)

    def test_13_human_approval_requirements(self):
        """13. Flagged documents require human staff approval to satisfy checklist items."""
        # Document with missing tax ID
        sparse_content = b"Sparse document with no EIN and missing entity details."
        uploaded = SimpleUploadedFile("incomplete_doc.txt", sparse_content, content_type="text/plain")
        
        tax_checklist_item = self.case.checklist_items.filter(category=ChecklistCategory.DOCUMENT_UPLOAD, title__icontains='tax').first()
        
        doc = Document.objects.create(
            case=self.case,
            checklist_item=tax_checklist_item,
            file=uploaded,
            file_name="incomplete_doc.txt",
            document_type_hint="tax_form",
            status=DocumentStatus.UPLOADED,
        )

        handle_process_uploaded_document({"document_id": str(doc.id), "case_id": str(self.case.id)})
        doc.refresh_from_db()

        # Should be flagged for human review
        self.assertEqual(doc.status, DocumentStatus.REVIEW_REQUIRED)
        self.assertFalse(doc.is_approved)
        self.assertFalse(tax_checklist_item.is_completed)

        # Staff logs in and approves document
        self.http_client.login(username="staff1", password="password123")
        review_url = reverse('document_review', kwargs={'document_id': doc.id})
        post_data = {
            'action': 'approve',
            'review_notes': 'Manually verified business registry.',
        }
        resp = self.http_client.post(review_url, post_data)
        self.assertEqual(resp.status_code, 302)

        doc.refresh_from_db()
        self.assertTrue(doc.is_approved)
        self.assertEqual(doc.status, DocumentStatus.APPROVED)
        self.assertEqual(doc.reviewed_by, self.staff_user)

        # Checklist item should now be completed
        tax_checklist_item.refresh_from_db()
        self.assertTrue(tax_checklist_item.is_completed)

    def test_private_document_access_security(self):
        """Unauthenticated requests without token cannot download private documents."""
        uploaded = SimpleUploadedFile("private.txt", b"Secret data", content_type="text/plain")
        doc = Document.objects.create(case=self.case, file=uploaded, file_name="private.txt")

        download_url = reverse('download_document', kwargs={'document_id': doc.id})
        
        # Unauthenticated request without token -> 403 Forbidden
        anon_res = self.http_client.get(download_url)
        self.assertEqual(anon_res.status_code, 403)

        # Authenticated staff request -> 200 OK
        self.http_client.login(username="staff1", password="password123")
        auth_res = self.http_client.get(download_url)
        self.assertEqual(auth_res.status_code, 200)
        self.assertEqual(auth_res.content, b"Secret data")

        # Client request WITH token -> 200 OK
        self.http_client.logout()
        token_res = self.http_client.get(f"{download_url}?token={self.case.client_access_token}")
        self.assertEqual(token_res.status_code, 200)
        self.assertEqual(token_res.content, b"Secret data")
