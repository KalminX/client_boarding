import json
import logging
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib import messages
from django.conf import settings
from django.core.paginator import Paginator

from .models import Contract, ContractStatus
from clients.models import Client
from onboarding.services import initialize_onboarding_for_signed_contract

logger = logging.getLogger(__name__)

@login_required
def contract_list_view(request):
    contracts = Contract.objects.select_related('client').all()
    status_filter = request.GET.get('status')
    if status_filter:
        contracts = contracts.filter(status=status_filter)

    paginator = Paginator(contracts, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'contracts/contract_list.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
    })


@login_required
def contract_detail_view(request, contract_id):
    contract = get_object_or_404(Contract.objects.select_related('client'), id=contract_id)
    onboarding_case = getattr(contract, 'onboarding_case', None)
    return render(request, 'contracts/contract_detail.html', {
        'contract': contract,
        'onboarding_case': onboarding_case,
    })


@login_required
def contract_create_view(request):
    clients = Client.objects.filter(is_active=True)
    if request.method == 'POST':
        client_id = request.POST.get('client_id')
        title = request.POST.get('title', 'Master Services Agreement')
        contract_value = request.POST.get('contract_value', '0.00')
        terms = request.POST.get('terms_summary', '')

        client = get_object_or_404(Client, id=client_id)
        contract = Contract.objects.create(
            client=client,
            title=title,
            contract_value=Decimal(contract_value or '0.00'),
            terms_summary=terms,
            status=ContractStatus.SENT,
        )
        messages.success(request, f"Contract '{contract.title}' created and marked as sent for signature.")
        return redirect('contract_detail', contract_id=contract.id)

    return render(request, 'contracts/contract_form.html', {'clients': clients})


@login_required
def sign_contract_action(request, contract_id):
    """
    Staff action to execute contract signature and kick off the automated onboarding pipeline.
    """
    if request.method != 'POST':
        return redirect('contract_detail', contract_id=contract_id)

    contract = get_object_or_404(Contract, id=contract_id)
    signer_name = request.POST.get('signer_name', contract.client.name)
    signer_email = request.POST.get('signer_email', contract.client.primary_email)

    case, created = initialize_onboarding_for_signed_contract(
        contract=contract,
        signed_by_name=signer_name,
        signed_by_email=signer_email,
        staff_user=request.user,
        ip_address=request.META.get('REMOTE_ADDR')
    )

    if created:
        messages.success(request, f"Contract successfully signed! Onboarding case #{case.id} created and initialization jobs queued.")
    else:
        messages.info(request, f"Contract signed. Linked to existing onboarding case #{case.id}.")

    return redirect('onboarding_detail', case_id=case.id)


@csrf_exempt
def webhook_contract_signed(request):
    """
    Simulated or real e-signature webhook endpoint (e.g. DocuSign / HelloSign / PandaDoc).
    Validates webhook secret and idempotently triggers onboarding.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("Method not allowed. Only POST is supported.")

    # Authenticate webhook secret
    shared_secret = getattr(settings, 'WEBHOOK_SHARED_SECRET', '')
    provided_secret = request.headers.get('X-Webhook-Secret') or request.GET.get('secret')
    
    if shared_secret and provided_secret != shared_secret:
        logger.warning("Webhook authentication failed. Invalid secret.")
        return HttpResponseForbidden("Invalid or missing webhook signature/secret.")

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON payload.")

    contract_id = data.get('contract_id')
    if not contract_id:
        return HttpResponseBadRequest("Missing 'contract_id' in webhook payload.")

    contract = Contract.objects.filter(id=contract_id).first()
    if not contract:
        return JsonResponse({"error": f"Contract {contract_id} not found"}, status=404)

    signer_name = data.get('signed_by_name', contract.client.name)
    signer_email = data.get('signed_by_email', contract.client.primary_email)

    case, created = initialize_onboarding_for_signed_contract(
        contract=contract,
        signed_by_name=signer_name,
        signed_by_email=signer_email,
        ip_address=request.META.get('REMOTE_ADDR')
    )

    return JsonResponse({
        "status": "success",
        "contract_id": str(contract.id),
        "case_id": str(case.id),
        "created_new_case": created,
        "message": "Onboarding pipeline triggered successfully."
    })
