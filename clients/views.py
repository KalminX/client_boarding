from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from .models import Client

@login_required
def client_list_view(request):
    search_query = request.GET.get('q', '').strip()
    clients = Client.objects.all()
    if search_query:
        clients = clients.filter(company_name__icontains=search_query) | clients.filter(name__icontains=search_query) | clients.filter(primary_email__icontains=search_query)

    paginator = Paginator(clients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'clients/client_list.html', {
        'page_obj': page_obj,
        'search_query': search_query,
    })


@login_required
def client_detail_view(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    contracts = client.contracts.all()
    onboarding_cases = client.onboarding_cases.all()
    return render(request, 'clients/client_detail.html', {
        'client': client,
        'contracts': contracts,
        'onboarding_cases': onboarding_cases,
    })


@login_required
def client_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        company_name = request.POST.get('company_name')
        primary_email = request.POST.get('primary_email')
        phone = request.POST.get('phone', '')
        billing_address = request.POST.get('billing_address', '')
        website = request.POST.get('website', '')
        industry = request.POST.get('industry', '')

        if not name or not company_name or not primary_email:
            messages.error(request, "Name, Company Name, and Email are required.")
            return render(request, 'clients/client_form.html')

        client = Client.objects.create(
            name=name,
            company_name=company_name,
            primary_email=primary_email,
            phone=phone,
            billing_address=billing_address,
            website=website,
            industry=industry,
        )
        messages.success(request, f"Client {client.company_name} created successfully.")
        return redirect('client_detail', client_id=client.id)

    return render(request, 'clients/client_form.html')
