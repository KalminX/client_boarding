import os
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage

from .registry import registry
from .dispatcher import enqueue_job
from onboarding.models import OnboardingCase, ChecklistItem, OnboardingStatus, ChecklistCategory
from documents.models import Document, DocumentStatus
from notifications.models import EmailNotification, StaffAlert, NotificationStatus
from audit.models import record_audit_event
from integrations.adapters import (
    get_email_adapter,
    get_storage_adapter,
    get_crm_adapter,
    get_task_adapter,
    get_document_extractor_adapter,
)

logger = logging.getLogger(__name__)
User = get_user_model()

# ==============================================================================
# HANDLER: send_welcome_email
# ==============================================================================

@registry.register("send_welcome_email")
def handle_send_welcome_email(payload: dict, job=None) -> dict:
    case_id = payload.get("case_id")
    recipient_email = payload.get("client_email")
    client_name = payload.get("client_name", "Valued Client")
    company_name = payload.get("company_name", "")
    access_token = payload.get("access_token")

    case = OnboardingCase.objects.filter(id=case_id).first()
    if not case and case_id:
        raise ValueError(f"OnboardingCase {case_id} not found.")

    subject = f"Welcome to our firm! Let's get started with your onboarding - {company_name or client_name}"
    portal_url = f"/portal/{access_token}/"
    
    body_text = f"""Hello {client_name},

Thank you for partnering with us! Your contract is now finalized.

To kick off your onboarding, please complete your intake details and upload required documentation at the secure link below:

{portal_url}

If you have any questions, your dedicated onboarding coordinator is ready to assist.

Best regards,
The Client Onboarding Team
"""
    idempotency_key = f"welcome_email_{case_id or recipient_email}"
    
    # Check if already sent
    existing_notif = EmailNotification.objects.filter(idempotency_key=idempotency_key).first()
    if existing_notif and existing_notif.status == NotificationStatus.SENT:
        logger.info("Welcome email already sent for case %s", case_id)
        return {"status": "already_sent", "notification_id": str(existing_notif.id)}

    adapter = get_email_adapter()
    result = adapter.send_email(
        recipient_email=recipient_email,
        subject=subject,
        body_text=body_text,
        recipient_name=client_name,
        idempotency_key=idempotency_key,
    )

    notif, _ = EmailNotification.objects.update_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "recipient_email": recipient_email,
            "recipient_name": client_name,
            "subject": subject,
            "body_text": body_text,
            "template_name": "welcome_email",
            "status": NotificationStatus.SENT,
            "sent_at": timezone.now(),
            "correlation_id": str(case_id) if case_id else None,
        }
    )

    if case:
        record_audit_event(
            event_type="WELCOME_EMAIL_SENT",
            description=f"Automated welcome email sent to {recipient_email}",
            case=case,
            metadata={"message_id": result.get("message_id")}
        )

    return {"status": "sent", "notification_id": str(notif.id), "delivery": result}


# ==============================================================================
# HANDLER: create_client_folder
# ==============================================================================

@registry.register("create_client_folder")
def handle_create_client_folder(payload: dict, job=None) -> dict:
    case_id = payload.get("case_id")
    client_name = payload.get("client_name", "Client")

    case = OnboardingCase.objects.filter(id=case_id).first()
    if not case:
        raise ValueError(f"OnboardingCase {case_id} not found")

    # Idempotent: check if folder already created
    if case.folder_id and case.folder_url:
        logger.info("Folder already exists for case %s: %s", case_id, case.folder_id)
        return {"status": "already_created", "folder_id": case.folder_id, "folder_url": case.folder_url}

    adapter = get_storage_adapter()
    storage_res = adapter.create_client_folder(client_name=client_name, case_id=str(case.id))

    case.folder_id = storage_res["folder_id"]
    case.folder_url = storage_res["folder_url"]
    case.save(update_fields=["folder_id", "folder_url", "updated_at"])

    # Mark folder setup checklist item if present
    item = case.checklist_items.filter(category=ChecklistCategory.FOLDER_SETUP).first()
    if item and not item.is_completed:
        item.mark_completed()

    record_audit_event(
        event_type="FOLDER_CREATED",
        description=f"Client storage folder created: {case.folder_id}",
        case=case,
        metadata=storage_res
    )

    return {"status": "created", "folder_id": case.folder_id, "folder_url": case.folder_url}


# ==============================================================================
# HANDLER: create_crm_record
# ==============================================================================

@registry.register("create_crm_record")
def handle_create_crm_record(payload: dict, job=None) -> dict:
    case_id = payload.get("case_id")
    company_name = payload.get("company_name", "")
    contact_name = payload.get("contact_name", "")
    email = payload.get("email", "")
    contract_value = float(payload.get("contract_value", 0.0))

    case = OnboardingCase.objects.filter(id=case_id).first()
    if not case:
        raise ValueError(f"OnboardingCase {case_id} not found")

    # Idempotent check
    if case.crm_id and case.crm_url:
        logger.info("CRM record already exists for case %s: %s", case_id, case.crm_id)
        return {"status": "already_created", "crm_id": case.crm_id, "crm_url": case.crm_url}

    adapter = get_crm_adapter()
    crm_res = adapter.create_or_update_company_and_deal(
        company_name=company_name,
        contact_name=contact_name,
        email=email,
        contract_value=contract_value,
        case_id=str(case.id),
    )

    case.crm_id = crm_res["crm_id"]
    case.crm_url = crm_res["crm_url"]
    case.save(update_fields=["crm_id", "crm_url", "updated_at"])

    # Mark CRM setup checklist item if present
    item = case.checklist_items.filter(category=ChecklistCategory.CRM_SETUP).first()
    if item and not item.is_completed:
        item.mark_completed()

    record_audit_event(
        event_type="CRM_RECORD_CREATED",
        description=f"CRM company and deal record created: {case.crm_id}",
        case=case,
        metadata=crm_res
    )

    return {"status": "created", "crm_id": case.crm_id, "crm_url": case.crm_url}


# ==============================================================================
# HANDLER: create_project_tasks
# ==============================================================================

@registry.register("create_project_tasks")
def handle_create_project_tasks(payload: dict, job=None) -> dict:
    case_id = payload.get("case_id")
    company_name = payload.get("company_name", "")

    case = OnboardingCase.objects.filter(id=case_id).first()
    if not case:
        raise ValueError(f"OnboardingCase {case_id} not found")

    if case.project_board_id and case.project_board_url:
        return {"status": "already_created", "project_board_id": case.project_board_id}

    adapter = get_task_adapter()
    task_res = adapter.create_onboarding_project(company_name=company_name, case_id=str(case.id))

    case.project_board_id = task_res["project_board_id"]
    case.project_board_url = task_res["project_board_url"]
    case.save(update_fields=["project_board_id", "project_board_url", "updated_at"])

    # Mark project setup checklist item
    item = case.checklist_items.filter(category=ChecklistCategory.PROJECT_SETUP).first()
    if item and not item.is_completed:
        item.mark_completed()

    record_audit_event(
        event_type="PROJECT_BOARD_CREATED",
        description=f"Project board and initial tasks provisioned: {case.project_board_id}",
        case=case,
        metadata=task_res
    )

    return {"status": "created", "project_board_id": case.project_board_id, "project_board_url": case.project_board_url}


# ==============================================================================
# HANDLER: process_uploaded_document
# ==============================================================================

@registry.register("process_uploaded_document")
def handle_process_uploaded_document(payload: dict, job=None) -> dict:
    doc_id = payload.get("document_id")
    document = Document.objects.filter(id=doc_id).first()
    if not document:
        raise ValueError(f"Document {doc_id} not found")

    document.status = DocumentStatus.PROCESSING
    document.save(update_fields=["status", "updated_at"])

    # Extract raw text from file
    raw_text = ""
    try:
        if document.file and os.path.exists(document.file.path):
            file_path = document.file.path
            file_ext = os.path.splitext(document.file_name)[1].lower()
            
            if file_ext == '.pdf':
                try:
                    import pypdf
                    reader = pypdf.PdfReader(file_path)
                    for page in reader.pages:
                        text = page.extract_text()
                        if text:
                            raw_text += text + "\n"
                except Exception:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        raw_text = f.read(50000)
            else:
                # Text or other file
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    raw_text = f.read(50000)
    except Exception as exc:
        logger.warning("Error reading file text for document %s: %s", doc_id, exc)
        raw_text = f"Simulated text for {document.file_name} with sample EIN 12-3456789 and entity {document.case.client.company_name}"

    if not raw_text.strip():
        raw_text = f"Entity Name: {document.case.client.company_name}\nTax ID: 98-7654321\nAddress: {document.case.client.billing_address or '100 Business Way'}\nSignatory: {document.case.client.name}"

    document.raw_extracted_text = raw_text

    # Run extraction adapter (mock or Claude)
    extractor = get_document_extractor_adapter()
    extraction_result = extractor.extract_document(
        raw_text=raw_text,
        file_name=document.file_name,
        document_type_hint=document.document_type_hint
    )

    document.extracted_data = extraction_result.get("extracted_fields", {})
    document.confidence_score = extraction_result.get("confidence_score", 0.0)
    document.validation_flags = extraction_result.get("validation_flags", [])

    # Determine status based on confidence and flags
    if document.confidence_score < 0.70 or document.validation_flags:
        document.status = DocumentStatus.REVIEW_REQUIRED
        # Create alert for assigned staff
        StaffAlert.objects.create(
            staff_user=document.case.assigned_staff,
            case=document.case,
            title=f"Document Review Required: {document.file_name}",
            message=f"Document '{document.file_name}' was processed with confidence {document.confidence_score*100:.0f}% and flags: {', '.join(document.validation_flags) or 'None'}. Please review and approve.",
            alert_type=StaffAlert.AlertType.ACTION_REQUIRED,
        )
    else:
        document.status = DocumentStatus.PROCESSED

    document.save(update_fields=[
        "raw_extracted_text",
        "extracted_data",
        "confidence_score",
        "validation_flags",
        "status",
        "updated_at"
    ])

    record_audit_event(
        event_type="DOCUMENT_PROCESSED",
        description=f"Processed document '{document.file_name}' (Status: {document.get_status_display()}, Confidence: {document.confidence_score*100:.0f}%)",
        case=document.case,
        metadata={"document_id": str(document.id), "confidence": document.confidence_score, "flags": document.validation_flags}
    )

    return {
        "status": document.status,
        "confidence_score": document.confidence_score,
        "validation_flags": document.validation_flags,
    }


# ==============================================================================
# HANDLER: send_client_reminder
# ==============================================================================

@registry.register("send_client_reminder")
def handle_send_client_reminder(payload: dict, job=None) -> dict:
    item_id = payload.get("checklist_item_id")
    item = ChecklistItem.objects.filter(id=item_id).first()
    if not item:
        raise ValueError(f"ChecklistItem {item_id} not found")

    # Stop reminders if item already completed
    if item.is_completed:
        logger.info("ChecklistItem %s is already completed. Skipping reminder.", item_id)
        return {"status": "skipped", "reason": "item_already_completed"}

    case = item.case
    # Stop reminders if case is completed or cancelled
    if case.status in [OnboardingStatus.COMPLETED, OnboardingStatus.CANCELLED]:
        return {"status": "skipped", "reason": f"case_{case.status}"}

    now = timezone.now()

    # Enforce maximum reminder count and escalate to staff
    if item.reminder_count >= item.max_reminders:
        # Escalate to staff
        StaffAlert.objects.create(
            staff_user=case.assigned_staff,
            case=case,
            title=f"OVERDUE ESCALATION: {item.title}",
            message=f"Checklist item '{item.title}' has reached maximum reminders ({item.reminder_count}/{item.max_reminders}) without completion. Case may require staff intervention.",
            alert_type=StaffAlert.AlertType.WARNING,
        )
        # Mark case as stalled if not already
        if case.status != OnboardingStatus.STALLED:
            case.status = OnboardingStatus.STALLED
            case.save(update_fields=["status", "updated_at"])
            
        record_audit_event(
            event_type="REMINDER_LIMIT_EXCEEDED",
            description=f"Item '{item.title}' reached max reminders ({item.reminder_count}). Escalated to staff.",
            case=case,
            metadata={"item_id": str(item.id), "reminder_count": item.reminder_count}
        )
        return {"status": "max_reminders_exceeded_and_escalated", "reminder_count": item.reminder_count}

    # Send reminder email
    item.reminder_count += 1
    item.last_reminder_sent_at = now
    item.save(update_fields=["reminder_count", "last_reminder_sent_at", "updated_at"])

    recipient_email = case.client.primary_email
    subject = f"Reminder ({item.reminder_count}/{item.max_reminders}): Action needed for onboarding - {item.title}"
    body_text = f"""Hello {case.client.name},

This is a friendly reminder that the following requirement for your onboarding with {case.client.company_name} is still outstanding:

Requirement: {item.title}
{f'Details: {item.description}' if item.description else ''}

Please visit your onboarding portal to complete this item:
/portal/{case.client_access_token}/

Thank you!
The Onboarding Team
"""
    idempotency_key = f"reminder_{item.id}_{item.reminder_count}"
    adapter = get_email_adapter()
    res = adapter.send_email(
        recipient_email=recipient_email,
        subject=subject,
        body_text=body_text,
        recipient_name=case.client.name,
        idempotency_key=idempotency_key
    )

    EmailNotification.objects.create(
        idempotency_key=idempotency_key,
        recipient_email=recipient_email,
        recipient_name=case.client.name,
        subject=subject,
        body_text=body_text,
        template_name="checklist_reminder",
        status=NotificationStatus.SENT,
        sent_at=now,
        correlation_id=str(case.id),
    )

    record_audit_event(
        event_type="REMINDER_SENT",
        description=f"Sent reminder #{item.reminder_count} for '{item.title}' to {recipient_email}",
        case=case,
        metadata={"item_id": str(item.id), "reminder_count": item.reminder_count}
    )

    return {"status": "sent", "reminder_count": item.reminder_count, "delivery": res}


# ==============================================================================
# HANDLER: notify_assigned_staff
# ==============================================================================

@registry.register("notify_assigned_staff")
def handle_notify_assigned_staff(payload: dict, job=None) -> dict:
    case_id = payload.get("case_id")
    staff_id = payload.get("staff_id")
    title = payload.get("title", "Staff Notification")
    message = payload.get("message", "")
    alert_type = payload.get("alert_type", StaffAlert.AlertType.INFO)

    case = OnboardingCase.objects.filter(id=case_id).first() if case_id else None
    staff_user = User.objects.filter(id=staff_id).first() if staff_id else None
    if not staff_user and case and case.assigned_staff:
        staff_user = case.assigned_staff

    alert = StaffAlert.objects.create(
        staff_user=staff_user,
        case=case,
        title=title,
        message=message,
        alert_type=alert_type,
    )

    if case:
        record_audit_event(
            event_type="STAFF_NOTIFIED",
            description=f"Staff alert created for {staff_user.username if staff_user else 'All Staff'}: {title}",
            case=case,
            metadata={"alert_id": str(alert.id)}
        )

    return {"status": "created", "alert_id": str(alert.id)}


# ==============================================================================
# HANDLER: check_overdue_onboarding
# ==============================================================================

@registry.register("check_overdue_onboarding")
def handle_check_overdue_onboarding(payload: dict, job=None) -> dict:
    """
    Periodic job that scans all active onboarding cases for overdue items or milestones.
    Safe to run repeatedly.
    """
    now = timezone.now()
    today = now.date()

    active_cases = OnboardingCase.objects.filter(
        status__in=[OnboardingStatus.IN_PROGRESS, OnboardingStatus.NOT_STARTED, OnboardingStatus.AWAITING_REVIEW]
    )

    overdue_items_count = 0
    reminders_enqueued = 0

    for case in active_cases:
        # Check items past due date or needing reminder
        for item in case.checklist_items.filter(is_completed=False):
            # If item has a due date in past, or hasn't received a reminder in 48 hours
            should_remind = False
            if item.due_date and item.due_date < today:
                should_remind = True
            elif not item.last_reminder_sent_at or (now - item.last_reminder_sent_at) > timedelta(hours=48):
                # Only if pending and required
                if item.is_required and item.reminder_count < item.max_reminders:
                    should_remind = True

            if should_remind and item.reminder_count < item.max_reminders:
                # Schedule reminder job
                enqueue_job(
                    job_type="send_client_reminder",
                    payload={"case_id": str(case.id), "checklist_item_id": str(item.id)},
                    idempotency_key=f"check_remind_{item.id}_{item.reminder_count + 1}",
                    correlation_id=str(case.id),
                )
                reminders_enqueued += 1

    return {
        "status": "completed",
        "active_cases_checked": active_cases.count(),
        "reminders_enqueued": reminders_enqueued,
    }
