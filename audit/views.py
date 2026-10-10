from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from .models import AuditEvent

@login_required
def audit_log_view(request):
    event_type = request.GET.get('event_type')
    case_id = request.GET.get('case_id')
    
    events = AuditEvent.objects.select_related('case', 'user', 'case__client').all().order_by('-timestamp')
    if event_type:
        events = events.filter(event_type=event_type)
    if case_id:
        events = events.filter(case__id=case_id)

    paginator = Paginator(events, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    event_types = AuditEvent.objects.values_list('event_type', flat=True).distinct()

    return render(request, 'audit/audit_log.html', {
        'page_obj': page_obj,
        'event_types': event_types,
        'selected_event_type': event_type or '',
        'selected_case_id': case_id or '',
    })
