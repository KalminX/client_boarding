import json
from decimal import Decimal
from django.test import TestCase, Client as HttpClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.conf import settings

from clients.models import Client
from contracts.models import Contract, ContractStatus
from onboarding.models import OnboardingCase, ChecklistItem, OnboardingStatus, ChecklistCategory, ClientIntakeSubmission
from onboarding.services import initialize_onboarding_for_signed_contract, check_and_update_case_completion
from workflow_engine.models import Job, JobStatus
from workflow_engine.worker import JobWorker
from notifications.models import EmailNotification, StaffAlert

User = get_user_model()

class OnboardingWorkflowIntegrationTests(TestCase):
    def setUp(self):
        self.http_client = HttpClient()
        self.staff_user = User.objects.create_user(username="teststaff", password="password123", is_staff=True)
        
        self.client_obj = Client.objects.create(
            name="Alice Smith",
            company_name="Acme Corp",
            primary_email="alice@acmecorp.com",
            billing_address="123 Market St, Suite 100",
        )

        self.contract = Contract.objects.create(
            client=self.client_obj,
            title="Enterprise Services Contract 2026",
            contract_value=Decimal("50000.00"),
            status=ContractStatus.SENT,
        )

    def test_09_and_10_complete_onboarding_init_and_duplicate_signature(self):
        """9 & 10. Complete onboarding initialization and protection against duplicate signing events."""
        # Initial signing
        case1, created1 = initialize_onboarding_for_signed_contract(
            contract=self.contract,
            signed_by_name="Alice Smith",
            signed_by_email="alice@acmecorp.com",
            staff_user=self.staff_user
        )
        self.assertTrue(created1)
        self.assertEqual(case1.status, OnboardingStatus.IN_PROGRESS)
        self.assertEqual(case1.client, self.client_obj)
        self.assertEqual(self.contract.status, ContractStatus.SIGNED)

        # Verify checklist items created
        items = case1.checklist_items.all()
        self.assertGreaterEqual(items.count(), 6)
        required_items = items.filter(is_required=True)
        self.assertTrue(required_items.exists())

        # Verify background jobs queued in database
        queued_jobs = Job.objects.filter(correlation_id=str(case1.id))
        job_types = set(queued_jobs.values_list('job_type', flat=True))
        self.assertIn("send_welcome_email", job_types)
        self.assertIn("create_client_folder", job_types)
        self.assertIn("create_crm_record", job_types)
        self.assertIn("create_project_tasks", job_types)

        # Duplicate signing event must NOT create duplicate cases or duplicate jobs
        case2, created2 = initialize_onboarding_for_signed_contract(
            contract=self.contract,
            signed_by_name="Alice Smith",
            signed_by_email="alice@acmecorp.com",
            staff_user=self.staff_user
        )
        self.assertFalse(created2)
        self.assertEqual(case1.id, case2.id)
        self.assertEqual(OnboardingCase.objects.filter(contract=self.contract).count(), 1)

        # Execute jobs using worker
        worker = JobWorker(poll_interval=0.1)
        worker.run(once=True)

        case1.refresh_from_db()
        self.assertIsNotNone(case1.folder_id)
        self.assertIsNotNone(case1.crm_id)
        self.assertIsNotNone(case1.project_board_id)

    def test_11_reminder_scheduling_and_suppression(self):
        """11. Reminder incrementing, limit escalation, and suppression upon completion."""
        case, _ = initialize_onboarding_for_signed_contract(self.contract, staff_user=self.staff_user)
        item = case.checklist_items.filter(category=ChecklistCategory.INTAKE_FORM).first()
        self.assertEqual(item.reminder_count, 0)

        # Execute reminder handler directly via registry
        from workflow_engine.handlers import handle_send_client_reminder
        res1 = handle_send_client_reminder({"checklist_item_id": str(item.id)})
        self.assertEqual(res1["status"], "sent")
        self.assertEqual(res1["reminder_count"], 1)

        item.refresh_from_db()
        self.assertEqual(item.reminder_count, 1)

        # Now mark item as completed
        item.mark_completed(user=self.staff_user)
        self.assertTrue(item.is_completed)

        # Subsequent reminder must be suppressed
        res_suppressed = handle_send_client_reminder({"checklist_item_id": str(item.id)})
        self.assertEqual(res_suppressed["status"], "skipped")
        self.assertEqual(res_suppressed["reason"], "item_already_completed")

    def test_14_client_data_isolation_and_portal_access(self):
        """14. Client data isolation using secure access token without staff auth."""
        case, _ = initialize_onboarding_for_signed_contract(self.contract, staff_user=self.staff_user)
        
        # Valid portal access
        portal_url = reverse('client_portal', kwargs={'access_token': case.client_access_token})
        response = self.http_client.get(portal_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acme Corp")

        # Invalid token returns 404
        bad_response = self.http_client.get(reverse('client_portal', kwargs={'access_token': 'nonexistent-invalid-token'}))
        self.assertEqual(bad_response.status_code, 404)

        # Submit intake form via portal
        submit_url = reverse('client_portal_submit', kwargs={'access_token': case.client_access_token})
        post_data = {
            'company_legal_name': 'Acme Global Inc',
            'tax_id': '11-2233445',
            'billing_contact_name': 'Alice Smith',
            'billing_contact_email': 'alice@acmecorp.com',
            'billing_address': '456 Innovation Blvd, Suite 200',
            'primary_use_case': 'Automated enterprise workflows',
            'privacy_consent_given': 'on',
        }
        submit_res = self.http_client.post(submit_url, post_data)
        self.assertEqual(submit_res.status_code, 302)

        # Verify submission saved and checklist marked completed
        submission = ClientIntakeSubmission.objects.get(case=case)
        self.assertEqual(submission.company_legal_name, 'Acme Global Inc')
        intake_item = case.checklist_items.filter(category=ChecklistCategory.INTAKE_FORM).first()
        self.assertTrue(intake_item.is_completed)

    def test_15_webhook_authentication_and_idempotency(self):
        """15. Webhook authentication with shared secret and idempotent contract signing."""
        new_client = Client.objects.create(name="Bob", company_name="Beta Corp", primary_email="bob@beta.com")
        new_contract = Contract.objects.create(client=new_client, title="Beta MSA", contract_value=Decimal("15000.00"))

        webhook_url = reverse('webhook_contract_signed')
        valid_secret = getattr(settings, 'WEBHOOK_SHARED_SECRET', 'super-secret-webhook-signing-key-12345')

        # Unauthorized request without secret
        unauth_res = self.http_client.post(
            webhook_url,
            data=json.dumps({"contract_id": str(new_contract.id)}),
            content_type="application/json"
        )
        self.assertEqual(unauth_res.status_code, 403)

        # Authorized webhook request
        auth_res = self.http_client.post(
            webhook_url,
            data=json.dumps({
                "contract_id": str(new_contract.id),
                "signed_by_name": "Bob Beta",
                "signed_by_email": "bob@beta.com"
            }),
            content_type="application/json",
            HTTP_X_WEBHOOK_SECRET=valid_secret
        )
        self.assertEqual(auth_res.status_code, 200)
        data = auth_res.json()
        self.assertTrue(data["created_new_case"])

        # Duplicate webhook request returns 200 with created_new_case=False
        dup_res = self.http_client.post(
            webhook_url,
            data=json.dumps({
                "contract_id": str(new_contract.id),
                "signed_by_name": "Bob Beta",
                "signed_by_email": "bob@beta.com"
            }),
            content_type="application/json",
            HTTP_X_WEBHOOK_SECRET=valid_secret
        )
        self.assertEqual(dup_res.status_code, 200)
        self.assertFalse(dup_res.json()["created_new_case"])

    def test_16_dashboard_status_accuracy(self):
        """16. Dashboard statistics and metric accuracy."""
        case, _ = initialize_onboarding_for_signed_contract(self.contract, staff_user=self.staff_user)
        self.http_client.login(username="teststaff", password="password123")
        
        dash_res = self.http_client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, "Active Onboarding")
        self.assertContains(dash_res, "Acme Corp")
