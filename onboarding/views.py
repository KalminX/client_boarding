from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Count, Q

from .models import OnboardingCase, ChecklistItem, OnboardingStatus, ClientIntakeSubmission, ChecklistCategory
from .forms import ClientIntakeForm
from .services import check_and_update_case_completion
from contracts.models import Contract, ContractStatus
from workflow_engine.models import Job, JobStatus
from workflow_engine.dispatcher import enqueue_job
from notifications.models import EmailNotification, StaffAlert
from audit.models import AuditEvent, record_audit_event
from documents.models import Document, DocumentStatus
from documents.forms import DocumentUploadForm

@login_required
def dashboard_view(request):
    """
    Main operational onboarding status dashboard.
    """
    cases = OnboardingCase.objects.select_related('client', 'contract', 'assigned_staff').all()
    
    total_cases = cases.count()
    active_cases = cases.filter(status__in=[OnboardingStatus.IN_PROGRESS, OnboardingStatus.AWAITING_REVIEW, OnboardingStatus.NOT_STARTED]).count()
    completed_cases = cases.filter(status=OnboardingStatus.COMPLETED).count()
    stalled_cases = cases.filter(status=OnboardingStatus.STALLED).count()
    
    # Jobs summary
    pending_jobs_count = Job.objects.filter(status__in=[JobStatus.PENDING, JobStatus.RETRYING, JobStatus.RUNNING]).count()
    failed_jobs_count = Job.objects.filter(status=JobStatus.FAILED).count()
    recent_jobs = Job.objects.all().order_by('-created_at')[:8]
    
    # Staff alerts
    recent_alerts = StaffAlert.objects.filter(is_read=False).order_by('-created_at')[:5]
    
    # Recent audit events
    recent_audit_events = AuditEvent.objects.select_related('case', 'user').order_by('-timestamp')[:8]

    # Pending requirements
    pending_requirements_count = ChecklistItem.objects.filter(is_required=True, is_completed=False).count()

    # Recent cases
    recent_cases = cases.order_by('-created_at')[:6]

    return render(request, 'onboarding/dashboard.html', {
        'total_cases': total_cases,
        'active_cases': active_cases,
        'completed_cases': completed_cases,
        'stalled_cases': stalled_cases,
        'pending_jobs_count': pending_jobs_count,
        'failed_jobs_count': failed_jobs_count,
        'pending_requirements_count': pending_requirements_count,
        'recent_jobs': recent_jobs,
        'recent_alerts': recent_alerts,
        'recent_audit_events': recent_audit_events,
        'recent_cases': recent_cases,
    })


@login_required
def onboarding_list_view(request):
    cases = OnboardingCase.objects.select_related('client', 'contract', 'assigned_staff').all()
    status_filter = request.GET.get('status')
    if status_filter:
        cases = cases.filter(status=status_filter)

    paginator = Paginator(cases, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'onboarding/onboarding_list.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
    })


@login_required
def onboarding_detail_view(request, case_id):
    case = get_object_or_404(
        OnboardingCase.objects.select_related('client', 'contract', 'assigned_staff'),
        id=case_id
    )
    checklist_items = case.checklist_items.all().order_by('order', 'created_at')
    documents = case.documents.all().order_by('-created_at')
    intake_submission = getattr(case, 'intake_submission', None)
    jobs = Job.objects.filter(correlation_id=str(case.id)).order_by('-created_at')
    audit_events = case.audit_events.all().order_by('-timestamp')
    emails = EmailNotification.objects.filter(correlation_id=str(case.id)).order_by('-created_at')
    upload_form = DocumentUploadForm()

    return render(request, 'onboarding/onboarding_detail.html', {
        'case': case,
        'checklist_items': checklist_items,
        'documents': documents,
        'intake_submission': intake_submission,
        'jobs': jobs,
        'audit_events': audit_events,
        'emails': emails,
        'upload_form': upload_form,
    })


@login_required
def toggle_checklist_item(request, item_id):
    if request.method != 'POST':
        return redirect('dashboard')

    item = get_object_or_404(ChecklistItem, id=item_id)
    item.is_completed = not item.is_completed
    if item.is_completed:
        item.completed_at = timezone.now()
        item.completed_by = request.user
    else:
        item.completed_at = None
        item.completed_by = None
    item.save()

    record_audit_event(
        event_type="CHECKLIST_TOGGLED",
        description=f"Checklist item '{item.title}' marked as {'Completed' if item.is_completed else 'Incomplete'}",
        case=item.case,
        user=request.user
    )

    # Check if case ready to complete
    check_and_update_case_completion(item.case, acting_user=request.user)

    messages.success(request, f"Updated '{item.title}'")
    return redirect('onboarding_detail', case_id=item.case.id)


@login_required
def trigger_reminder_action(request, item_id):
    if request.method != 'POST':
        return redirect('dashboard')

    item = get_object_or_404(ChecklistItem, id=item_id)
    if item.is_completed:
        messages.warning(request, "This checklist item is already marked completed.")
        return redirect('onboarding_detail', case_id=item.case.id)

    # Queue reminder job
    job = enqueue_job(
        job_type="send_client_reminder",
        payload={"case_id": str(item.case.id), "checklist_item_id": str(item.id)},
        correlation_id=str(item.case.id),
        priority=10,
    )
    messages.success(request, f"Reminder job queued for '{item.title}' (Job ID: {job.id}).")
    return redirect('onboarding_detail', case_id=item.case.id)


@login_required
def complete_onboarding_action(request, case_id):
    if request.method != 'POST':
        return redirect('onboarding_detail', case_id=case_id)

    case = get_object_or_404(OnboardingCase, id=case_id)
    if not case.is_all_required_items_completed:
        messages.error(request, "Cannot complete onboarding: there are outstanding required checklist items.")
        return redirect('onboarding_detail', case_id=case_id)

    case.status = OnboardingStatus.COMPLETED
    case.completed_at = timezone.now()
    case.save(update_fields=['status', 'completed_at', 'updated_at'])

    # Mark manual review checklist item as completed
    review_item = case.checklist_items.filter(category=ChecklistCategory.MANUAL_REVIEW).first()
    if review_item and not review_item.is_completed:
        review_item.mark_completed(user=request.user)

    record_audit_event(
        event_type="ONBOARDING_MANUALLY_COMPLETED",
        description=f"Staff member {request.user.username} formally approved and completed the onboarding case.",
        case=case,
        user=request.user
    )

    messages.success(request, f"Onboarding case for {case.client.company_name} is now successfully COMPLETED!")
    return redirect('onboarding_detail', case_id=case_id)


# ==============================================================================
# CLIENT-FACING PORTAL VIEWS (TOKEN-AUTHENTICATED)
# ==============================================================================

def client_portal_view(request, access_token):
    case = get_object_or_404(
        OnboardingCase.objects.select_related('client', 'contract'),
        client_access_token=access_token
    )
    checklist_items = case.checklist_items.all().order_by('order')
    intake_submission = getattr(case, 'intake_submission', None)
    documents = case.documents.all().order_by('-created_at')

    # Initial form data prefilled from client profile
    initial_data = {
        'company_legal_name': case.client.company_name,
        'billing_contact_name': case.client.name,
        'billing_contact_email': case.client.primary_email,
        'billing_address': case.client.billing_address,
    }
    intake_form = ClientIntakeForm(instance=intake_submission, initial=initial_data if not intake_submission else None)
    upload_form = DocumentUploadForm()

    return render(request, 'onboarding/client_portal.html', {
        'case': case,
        'checklist_items': checklist_items,
        'intake_submission': intake_submission,
        'intake_form': intake_form,
        'upload_form': upload_form,
        'documents': documents,
        'access_token': access_token,
    })


def client_portal_intake_submit(request, access_token):
    case = get_object_or_404(OnboardingCase, client_access_token=access_token)
    intake_instance = getattr(case, 'intake_submission', None)

    if request.method == 'POST':
        form = ClientIntakeForm(request.POST, instance=intake_instance)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.case = case
            submission.submitted_at = timezone.now()
            submission.save()

            # Mark intake checklist item as completed
            intake_item = case.checklist_items.filter(category=ChecklistCategory.INTAKE_FORM).first()
            if intake_item:
                intake_item.mark_completed()

            # Update client billing address and company name if provided
            case.client.billing_address = submission.billing_address
            if submission.company_legal_name:
                case.client.company_name = submission.company_legal_name
            case.client.save()

            # Enqueue staff alert
            enqueue_job(
                job_type="notify_assigned_staff",
                payload={
                    "case_id": str(case.id),
                    "staff_id": case.assigned_staff.id if case.assigned_staff else None,
                    "title": f"Intake Form Submitted: {case.client.company_name}",
                    "message": f"Client {case.client.name} has completed the onboarding intake questionnaire.",
                    "alert_type": "info",
                },
                correlation_id=str(case.id)
            )

            record_audit_event(
                event_type="INTAKE_FORM_SUBMITTED",
                description=f"Client intake form submitted for {case.client.company_name}",
                case=case,
                ip_address=request.META.get('REMOTE_ADDR')
            )

            # Check if all items complete
            check_and_update_case_completion(case)

            messages.success(request, "Your intake questionnaire has been successfully submitted! Thank you.")
            return redirect('client_portal', access_token=access_token)
        else:
            messages.error(request, "Please correct the highlighted errors in the form.")
            checklist_items = case.checklist_items.all().order_by('order')
            documents = case.documents.all().order_by('-created_at')
            return render(request, 'onboarding/client_portal.html', {
                'case': case,
                'checklist_items': checklist_items,
                'intake_submission': intake_instance,
                'intake_form': form,
                'upload_form': DocumentUploadForm(),
                'documents': documents,
                'access_token': access_token,
            })

    return redirect('client_portal', access_token=access_token)
