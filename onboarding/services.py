import logging
from datetime import timedelta
from typing import Optional, Tuple, Any
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from clients.models import Client
from contracts.models import Contract, ContractStatus
from onboarding.models import OnboardingCase, ChecklistItem, OnboardingStatus, ChecklistCategory
from workflow_engine.dispatcher import enqueue_job
from audit.models import record_audit_event

logger = logging.getLogger(__name__)
User = get_user_model()

def initialize_onboarding_for_signed_contract(
    contract: Contract,
    signed_by_name: str = "",
    signed_by_email: str = "",
    staff_user: Optional[Any] = None,
    ip_address: Optional[str] = None
) -> Tuple[OnboardingCase, bool]:
    """
    Executes transactional onboarding initialization upon contract signing.
    Creates or retrieves the OnboardingCase, checklist items, and durably enqueues background jobs.
    Protected against duplicate contract signing events.
    """
    with transaction.atomic():
        # 1. Update contract state if not already signed
        if contract.status != ContractStatus.SIGNED:
            contract.status = ContractStatus.SIGNED
            contract.signed_at = timezone.now()
            if signed_by_name:
                contract.signed_by_name = signed_by_name
            if signed_by_email:
                contract.signed_by_email = signed_by_email
            contract.save(update_fields=['status', 'signed_at', 'signed_by_name', 'signed_by_email', 'updated_at'])

        # 2. Check if onboarding case already exists for this contract
        existing_case = OnboardingCase.objects.filter(contract=contract).first()
        if existing_case:
            logger.info("Onboarding case already exists for contract %s (case %s). Skipping re-initialization.", contract.id, existing_case.id)
            return existing_case, False

        # Pick default staff member if none provided
        if not staff_user:
            staff_user = User.objects.filter(is_staff=True).first()

        now = timezone.now()
        target_date = (now + timedelta(days=14)).date()

        # 3. Create Onboarding Case
        case = OnboardingCase.objects.create(
            client=contract.client,
            contract=contract,
            status=OnboardingStatus.IN_PROGRESS,
            assigned_staff=staff_user,
            started_at=now,
            target_completion_date=target_date,
        )

        # 4. Create Standard Checklist Items
        items_data = [
            {
                "category": ChecklistCategory.INTAKE_FORM,
                "title": "Complete Client Intake Questionnaire",
                "description": "Provide company details, billing info, technical point of contact, and project requirements.",
                "is_required": True,
                "due_date": (now + timedelta(days=3)).date(),
                "order": 10,
            },
            {
                "category": ChecklistCategory.DOCUMENT_UPLOAD,
                "title": "Upload Tax Form / W9 or Company Registration",
                "description": "Upload a valid IRS Form W-9, certificate of incorporation, or official registration document.",
                "is_required": True,
                "due_date": (now + timedelta(days=5)).date(),
                "order": 20,
            },
            {
                "category": ChecklistCategory.DOCUMENT_UPLOAD,
                "title": "Upload Authorized Signatory Identification",
                "description": "Government-issued ID or authorization letter for primary account representative.",
                "is_required": False,
                "due_date": (now + timedelta(days=7)).date(),
                "order": 30,
            },
            {
                "category": ChecklistCategory.FOLDER_SETUP,
                "title": "Provision Client Storage Folder",
                "description": "Automated creation of secure document workspace.",
                "is_required": True,
                "order": 40,
            },
            {
                "category": ChecklistCategory.CRM_SETUP,
                "title": "Sync CRM Account & Deal Stage",
                "description": "Automated sync of deal value, contact details, and account hierarchy in CRM.",
                "is_required": True,
                "order": 50,
            },
            {
                "category": ChecklistCategory.PROJECT_SETUP,
                "title": "Initialize Onboarding Project Board & Tasks",
                "description": "Automated generation of kickoff project task list.",
                "is_required": True,
                "order": 60,
            },
            {
                "category": ChecklistCategory.MANUAL_REVIEW,
                "title": "Staff Final Review & Onboarding Completion Sign-off",
                "description": "Staff member verifies all requirements and approves formal onboarding completion.",
                "is_required": True,
                "order": 70,
            },
        ]

        for item_info in items_data:
            ChecklistItem.objects.create(case=case, **item_info)

        # 5. Durably enqueue background jobs inside the same transaction
        correlation_id = str(case.id)

        # Welcome Email
        enqueue_job(
            job_type="send_welcome_email",
            payload={
                "case_id": str(case.id),
                "client_email": contract.client.primary_email,
                "client_name": contract.client.name,
                "company_name": contract.client.company_name,
                "access_token": case.client_access_token,
            },
            idempotency_key=f"welcome_email_{case.id}",
            correlation_id=correlation_id,
            priority=10,
        )

        # Folder Setup
        enqueue_job(
            job_type="create_client_folder",
            payload={
                "case_id": str(case.id),
                "client_name": contract.client.company_name or contract.client.name,
            },
            idempotency_key=f"create_folder_{case.id}",
            correlation_id=correlation_id,
            priority=20,
        )

        # CRM Record
        enqueue_job(
            job_type="create_crm_record",
            payload={
                "case_id": str(case.id),
                "company_name": contract.client.company_name,
                "contact_name": contract.client.name,
                "email": contract.client.primary_email,
                "contract_value": float(contract.contract_value),
            },
            idempotency_key=f"create_crm_{case.id}",
            correlation_id=correlation_id,
            priority=20,
        )

        # Project Task Creation
        enqueue_job(
            job_type="create_project_tasks",
            payload={
                "case_id": str(case.id),
                "company_name": contract.client.company_name,
            },
            idempotency_key=f"create_tasks_{case.id}",
            correlation_id=correlation_id,
            priority=30,
        )

        # Staff Notification
        if staff_user:
            enqueue_job(
                job_type="notify_assigned_staff",
                payload={
                    "case_id": str(case.id),
                    "staff_id": staff_user.id,
                    "title": f"New Client Onboarding Assigned: {contract.client.company_name}",
                    "message": f"Contract for {contract.client.company_name} was signed for ${contract.contract_value:,.2f}. Onboarding case is initialized and tasks are queued.",
                    "alert_type": "action_required",
                },
                idempotency_key=f"staff_alert_init_{case.id}",
                correlation_id=correlation_id,
                priority=40,
            )

        # 6. Record Audit Event
        record_audit_event(
            event_type="ONBOARDING_INITIALIZED",
            description=f"Contract '{contract.title}' signed. Initialized onboarding case for {contract.client.company_name}.",
            case=case,
            user=staff_user,
            ip_address=ip_address,
            metadata={
                "contract_id": str(contract.id),
                "contract_value": float(contract.contract_value),
                "signed_by": signed_by_name or contract.client.name,
            }
        )

        logger.info("Successfully initialized onboarding case %s for contract %s", case.id, contract.id)
        return case, True


def check_and_update_case_completion(case: OnboardingCase, acting_user: Optional[Any] = None) -> bool:
    """
    Checks if all mandatory checklist items are completed and marks case as COMPLETED.
    Returns True if case was completed, False otherwise.
    """
    with transaction.atomic():
        case.refresh_from_db()
        if case.status == OnboardingStatus.COMPLETED:
            return True

        if not case.is_all_required_items_completed:
            return False

        case.status = OnboardingStatus.COMPLETED
        case.completed_at = timezone.now()
        case.save(update_fields=['status', 'completed_at', 'updated_at'])

        record_audit_event(
            event_type="ONBOARDING_COMPLETED",
            description=f"All requirements satisfied. Onboarding marked as COMPLETED for {case.client.company_name}.",
            case=case,
            user=acting_user,
        )

        return True
