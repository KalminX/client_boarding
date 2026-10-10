import os
import mimetypes
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.contrib import messages
from django.utils import timezone
from django.conf import settings

from .models import Document, DocumentStatus
from .forms import DocumentUploadForm, DocumentReviewForm
from onboarding.models import OnboardingCase, ChecklistCategory
from onboarding.services import check_and_update_case_completion
from workflow_engine.dispatcher import enqueue_job
from audit.models import record_audit_event

def upload_document_view(request, case_id):
    """
    Handles document upload from either staff detail view or client portal.
    """
    case = get_object_or_404(OnboardingCase, id=case_id)
    token = request.POST.get('access_token') or request.GET.get('access_token')

    # Security check: User must be authenticated staff OR have the valid case access token
    if not request.user.is_authenticated and case.client_access_token != token:
        return HttpResponseForbidden("Access denied. Invalid token or unauthenticated session.")

    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data['file']
            hint = form.cleaned_data['document_type_hint']

            # Find matching checklist item if applicable
            checklist_item = None
            if hint in ['tax_form', 'w9']:
                checklist_item = case.checklist_items.filter(category=ChecklistCategory.DOCUMENT_UPLOAD, title__icontains='tax').first()
            elif hint in ['id_proof']:
                checklist_item = case.checklist_items.filter(category=ChecklistCategory.DOCUMENT_UPLOAD, title__icontains='signatory').first()

            doc = Document.objects.create(
                case=case,
                checklist_item=checklist_item,
                file=uploaded_file,
                file_name=uploaded_file.name,
                file_type=uploaded_file.content_type or 'application/octet-stream',
                file_size_bytes=uploaded_file.size,
                document_type_hint=hint,
                status=DocumentStatus.UPLOADED,
            )

            # Durably enqueue background document extraction job
            enqueue_job(
                job_type="process_uploaded_document",
                payload={
                    "document_id": str(doc.id),
                    "case_id": str(case.id),
                },
                correlation_id=str(case.id),
                priority=15,
            )

            record_audit_event(
                event_type="DOCUMENT_UPLOADED",
                description=f"Uploaded file '{doc.file_name}' ({doc.document_type_hint})",
                case=case,
                user=request.user if request.user.is_authenticated else None,
                ip_address=request.META.get('REMOTE_ADDR'),
                metadata={"document_id": str(doc.id), "file_name": doc.file_name}
            )

            messages.success(request, f"Document '{doc.file_name}' uploaded successfully. Background data extraction queued.")

            if token:
                return redirect('client_portal', access_token=token)
            return redirect('onboarding_detail', case_id=case.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")

    if token:
        return redirect('client_portal', access_token=token)
    return redirect('onboarding_detail', case_id=case.id)


@login_required
def document_review_view(request, document_id):
    """
    Staff view to review AI-extracted data, confidence, flags, and record human approval.
    """
    document = get_object_or_404(
        Document.objects.select_related('case', 'case__client', 'checklist_item'),
        id=document_id
    )

    if request.method == 'POST':
        form = DocumentReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            notes = form.cleaned_data['review_notes']

            if action == 'approve':
                document.status = DocumentStatus.APPROVED
                document.is_approved = True
                document.reviewed_by = request.user
                document.reviewed_at = timezone.now()
                document.review_notes = notes
                document.save()

                # Mark associated checklist item as completed
                if document.checklist_item and not document.checklist_item.is_completed:
                    document.checklist_item.mark_completed(user=request.user)

                record_audit_event(
                    event_type="DOCUMENT_APPROVED",
                    description=f"Document '{document.file_name}' approved by {request.user.username}",
                    case=document.case,
                    user=request.user,
                    metadata={"document_id": str(document.id), "notes": notes}
                )

                # Check if case can complete
                check_and_update_case_completion(document.case, acting_user=request.user)
                messages.success(request, f"Document '{document.file_name}' has been APPROVED.")
            else:
                document.status = DocumentStatus.REJECTED
                document.is_approved = False
                document.reviewed_by = request.user
                document.reviewed_at = timezone.now()
                document.review_notes = notes
                document.save()

                record_audit_event(
                    event_type="DOCUMENT_REJECTED",
                    description=f"Document '{document.file_name}' rejected by {request.user.username}: {notes}",
                    case=document.case,
                    user=request.user,
                    metadata={"document_id": str(document.id), "notes": notes}
                )
                messages.warning(request, f"Document '{document.file_name}' has been REJECTED.")

            return redirect('onboarding_detail', case_id=document.case.id)

    form = DocumentReviewForm(initial={'review_notes': document.review_notes})
    return render(request, 'documents/document_review.html', {
        'document': document,
        'form': form,
    })


def download_private_document(request, document_id):
    """
    Secure file download view for private storage.
    Verifies staff authentication or client access token.
    """
    document = get_object_or_404(Document.objects.select_related('case'), id=document_id)
    token = request.GET.get('token')

    # Security check
    is_staff = request.user.is_authenticated and request.user.is_staff
    is_token_valid = token and document.case.client_access_token == token

    if not (is_staff or is_token_valid):
        return HttpResponseForbidden("Access denied. You do not have permission to access this document.")

    if not document.file or not os.path.exists(document.file.path):
        raise Http404("Document file not found on disk.")

    mime_type, _ = mimetypes.guess_type(document.file_name)
    mime_type = mime_type or 'application/octet-stream'

    with open(document.file.path, 'rb') as f:
        response = HttpResponse(f.read(), content_type=mime_type)
        response['Content-Disposition'] = f'inline; filename="{document.file_name}"'
        return response
