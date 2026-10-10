from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from clients.views import client_list_view, client_detail_view, client_create_view
from contracts.views import (
    contract_list_view, contract_detail_view, contract_create_view,
    sign_contract_action, webhook_contract_signed
)
from onboarding.views import (
    dashboard_view, onboarding_list_view, onboarding_detail_view,
    toggle_checklist_item, trigger_reminder_action, complete_onboarding_action,
    client_portal_view, client_portal_intake_submit
)
from documents.views import upload_document_view, document_review_view, download_private_document
from workflow_engine.views import job_monitor_view, retry_job_view, cancel_job_view, run_worker_once_view
from integrations.views import integrations_dashboard_view
from audit.views import audit_log_view

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Dashboard
    path('', dashboard_view, name='dashboard'),
    
    # Clients
    path('clients/', client_list_view, name='client_list'),
    path('clients/create/', client_create_view, name='client_create'),
    path('clients/<uuid:client_id>/', client_detail_view, name='client_detail'),
    
    # Contracts
    path('contracts/', contract_list_view, name='contract_list'),
    path('contracts/create/', contract_create_view, name='contract_create'),
    path('contracts/<uuid:contract_id>/', contract_detail_view, name='contract_detail'),
    path('contracts/<uuid:contract_id>/sign/', sign_contract_action, name='sign_contract'),
    
    # Onboarding Cases
    path('onboarding/', onboarding_list_view, name='onboarding_list'),
    path('onboarding/<uuid:case_id>/', onboarding_detail_view, name='onboarding_detail'),
    path('onboarding/<uuid:case_id>/complete/', complete_onboarding_action, name='complete_onboarding'),
    path('checklist/<uuid:item_id>/toggle/', toggle_checklist_item, name='toggle_checklist_item'),
    path('checklist/<uuid:item_id>/remind/', trigger_reminder_action, name='trigger_reminder'),
    
    # Client Portal (Token Authenticated)
    path('portal/<str:access_token>/', client_portal_view, name='client_portal'),
    path('portal/<str:access_token>/submit/', client_portal_intake_submit, name='client_portal_submit'),
    
    # Documents
    path('documents/upload/<uuid:case_id>/', upload_document_view, name='upload_document'),
    path('documents/<uuid:document_id>/review/', document_review_view, name='document_review'),
    path('documents/<uuid:document_id>/download/', download_private_document, name='download_document'),
    
    # Workflow Job Queue & Monitor
    path('jobs/', job_monitor_view, name='job_monitor'),
    path('jobs/<uuid:job_id>/retry/', retry_job_view, name='retry_job'),
    path('jobs/<uuid:job_id>/cancel/', cancel_job_view, name='cancel_job'),
    path('jobs/run-worker-once/', run_worker_once_view, name='run_worker_once'),
    
    # Integrations & Audit
    path('integrations/', integrations_dashboard_view, name='integrations_dashboard'),
    path('audit/', audit_log_view, name='audit_log'),
    
    # Webhooks
    path('api/webhooks/contract-signed/', webhook_contract_signed, name='webhook_contract_signed'),
]
