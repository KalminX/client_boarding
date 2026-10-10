from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from onboarding.models import OnboardingCase
from notifications.models import EmailNotification
from documents.models import Document

@login_required
def integrations_dashboard_view(request):
    """
    Overview of all external integrations activity and inspectable results.
    """
    cases_with_integrations = OnboardingCase.objects.select_related('client', 'contract').exclude(
        folder_id__isnull=True, crm_id__isnull=True, project_board_id__isnull=True
    ).order_by('-created_at')

    recent_emails = EmailNotification.objects.order_by('-created_at')[:15]
    recent_docs = Document.objects.select_related('case', 'case__client').order_by('-created_at')[:15]

    return render(request, 'integrations/integrations_dashboard.html', {
        'cases': cases_with_integrations,
        'recent_emails': recent_emails,
        'recent_docs': recent_docs,
    })
