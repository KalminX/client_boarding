import re
import json
import uuid
import hashlib
import logging
from typing import Dict, Any, List, Optional
from django.conf import settings
from django.core.mail import send_mail
from .interfaces import (
    EmailAdapterInterface,
    StorageAdapterInterface,
    CRMAdapterInterface,
    ProjectTaskAdapterInterface,
    DocumentExtractorInterface,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# EMAIL ADAPTERS
# ==============================================================================

class MockEmailAdapter(EmailAdapterInterface):
    """
    Mock email adapter that logs and generates inspectable simulated delivery metadata.
    """
    def send_email(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        recipient_name: str = "",
        body_html: str = "",
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        msg_hash = hashlib.md5(f"{recipient_email}:{subject}:{idempotency_key}".encode()).hexdigest()[:12]
        message_id = f"mock-msg-{msg_hash}"
        logger.info("[MockEmailAdapter] Sent email to <%s> ('%s'). Simulated Message ID: %s", recipient_email, subject, message_id)
        
        # If configured with console backend, also send through Django mail for console inspection
        try:
            send_mail(
                subject=subject,
                message=body_text,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'onboarding@example.com'),
                recipient_list=[recipient_email],
                fail_silently=True,
                html_message=body_html or None,
            )
        except Exception as e:
            logger.debug("Console email backend error (ignored in mock): %s", e)

        return {
            "status": "delivered",
            "message_id": message_id,
            "provider": "mock_email_service",
            "recipient": recipient_email,
            "subject": subject,
        }


# ==============================================================================
# STORAGE / FOLDER ADAPTERS
# ==============================================================================

class MockStorageAdapter(StorageAdapterInterface):
    """
    Mock Google Drive / Cloud Storage adapter generating simulated folder IDs and URLs.
    """
    def create_client_folder(self, client_name: str, case_id: str) -> Dict[str, Any]:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', client_name.lower())
        folder_id = f"gdrive_fld_{clean_name}_{case_id[:8]}"
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
        logger.info("[MockStorageAdapter] Created simulated client folder: %s (URL: %s)", folder_id, folder_url)
        return {
            "folder_id": folder_id,
            "folder_url": folder_url,
            "provider": "google_drive_mock",
            "created_path": f"/Clients/{client_name}/Onboarding-{case_id[:8]}",
        }


# ==============================================================================
# CRM ADAPTERS
# ==============================================================================

class MockCRMAdapter(CRMAdapterInterface):
    """
    Mock HubSpot / Salesforce adapter generating simulated CRM record IDs and links.
    """
    def create_or_update_company_and_deal(
        self,
        company_name: str,
        contact_name: str,
        email: str,
        contract_value: float,
        case_id: str
    ) -> Dict[str, Any]:
        slug = re.sub(r'[^a-zA-Z0-9]', '', company_name.lower())[:8]
        crm_id = f"hs_co_{slug}_{case_id[:6]}"
        deal_id = f"deal_{slug}_{case_id[:6]}"
        crm_url = f"https://app.hubspot.com/contacts/demo/company/{crm_id}"
        logger.info("[MockCRMAdapter] Synced company '%s' and deal '%s' in CRM (ID: %s)", company_name, deal_id, crm_id)
        return {
            "crm_id": crm_id,
            "deal_id": deal_id,
            "crm_url": crm_url,
            "provider": "hubspot_mock",
            "lifecycle_stage": "customer_onboarding",
            "deal_amount": contract_value,
        }


# ==============================================================================
# PROJECT TASK ADAPTERS
# ==============================================================================

class MockProjectTaskAdapter(ProjectTaskAdapterInterface):
    """
    Mock Asana / ClickUp adapter generating simulated project board and task lists.
    """
    def create_onboarding_project(
        self,
        company_name: str,
        case_id: str,
        tasks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        slug = re.sub(r'[^a-zA-Z0-9]', '', company_name.lower())[:8]
        project_board_id = f"asana_prj_{slug}_{case_id[:6]}"
        project_board_url = f"https://app.asana.com/0/{project_board_id}/list"
        
        default_tasks = [
            "Review signed contract and payment terms",
            "Schedule kickoff call with client team",
            "Provision client software seats & credentials",
            "Verify uploaded compliance and tax documents",
            "Deliver onboarding welcome package",
        ]
        task_names = [t.get('title', str(t)) if isinstance(t, dict) else str(t) for t in (tasks or default_tasks)]
        
        generated_tasks = [
            {"id": f"task_{idx}_{uuid.uuid4().hex[:6]}", "title": title, "status": "todo"}
            for idx, title in enumerate(task_names, start=1)
        ]
        
        logger.info("[MockProjectTaskAdapter] Created project board '%s' with %d tasks", project_board_id, len(generated_tasks))
        return {
            "project_board_id": project_board_id,
            "project_board_url": project_board_url,
            "provider": "asana_mock",
            "tasks_created_count": len(generated_tasks),
            "tasks": generated_tasks,
        }


# ==============================================================================
# DOCUMENT AI EXTRACTOR ADAPTERS
# ==============================================================================

class MockClaudeExtractorAdapter(DocumentExtractorInterface):
    """
    High-fidelity deterministic mock extractor for testing without API keys.
    Extracts text using patterns and generates structured output with confidence and validation flags.
    """
    def extract_document(
        self,
        raw_text: str,
        file_name: str,
        document_type_hint: str = "general"
    ) -> Dict[str, Any]:
        text_lower = raw_text.lower()
        extracted = {}
        flags = []
        confidence = 0.95

        # Extract Tax ID / EIN if found
        ein_match = re.search(r'\b(?:ein|tax\s*id|ssn)?\s*:?\s*(\d{2}-\d{7}|\d{9})\b', raw_text, re.IGNORECASE)
        if ein_match:
            extracted["tax_id"] = ein_match.group(1)
        else:
            if "w9" in file_name.lower() or "tax" in text_lower or document_type_hint in ["tax_form", "w9"]:
                flags.append("Missing Tax Identification Number (EIN/SSN)")
                confidence -= 0.2

        # Extract Legal Entity Name
        name_match = re.search(r'(?:legal\s*name|company\s*name|name\s*of\s*entity)\s*[:=]\s*([A-Za-z0-9\s,\.\-&]+)', raw_text, re.IGNORECASE)
        if name_match:
            extracted["entity_name"] = name_match.group(1).strip().split('\n')[0]
        else:
            extracted["entity_name"] = file_name.rsplit('.', 1)[0].replace('_', ' ').title()

        # Extract Address
        addr_match = re.search(r'(?:address|street|location)\s*[:=]\s*([A-Za-z0-9\s,\.\-#]+)', raw_text, re.IGNORECASE)
        if addr_match:
            extracted["address"] = addr_match.group(1).strip().split('\n')[0]

        # Extract Effective Date
        date_match = re.search(r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b', raw_text)
        if date_match:
            extracted["date_identified"] = date_match.group(1)

        # Extract Signatory
        sig_match = re.search(r'(?:signed\s*by|signatory|authorized\s*representative)\s*[:=]\s*([A-Za-z\s\.]+)', raw_text, re.IGNORECASE)
        if sig_match:
            extracted["authorized_signatory"] = sig_match.group(1).strip().split('\n')[0]

        # Fallback if document text is too sparse
        if len(raw_text.strip()) < 20:
            flags.append("Document text is sparse or unreadable; manual inspection required.")
            confidence = 0.35

        confidence = max(0.1, min(1.0, round(confidence, 2)))
        
        return {
            "extracted_fields": extracted,
            "confidence_score": confidence,
            "validation_flags": flags,
            "raw_summary": f"Extracted {len(extracted)} key fields from {file_name}. Flags: {len(flags)}.",
            "provider": "mock_claude_adapter",
        }


class AnthropicClaudeAdapter(DocumentExtractorInterface):
    """
    Real Claude API adapter using anthropic-sdk with safe error handling and fallback.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, 'ANTHROPIC_API_KEY', '')

    def extract_document(
        self,
        raw_text: str,
        file_name: str,
        document_type_hint: str = "general"
    ) -> Dict[str, Any]:
        if not self.api_key:
            logger.warning("No ANTHROPIC_API_KEY provided. Falling back to MockClaudeExtractorAdapter.")
            return MockClaudeExtractorAdapter().extract_document(raw_text, file_name, document_type_hint)

        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)

        prompt = f"""
You are a specialized document data extraction assistant for client onboarding.
Analyze the following document text and return a JSON object with structured entity information.

DOCUMENT FILE NAME: {file_name}
DOCUMENT TYPE HINT: {document_type_hint}

DOCUMENT TEXT:
\"\"\"
{raw_text[:12000]}
\"\"\"

Respond ONLY with a valid JSON object strictly matching this schema:
{{
  "extracted_fields": {{
    "entity_name": "...",
    "tax_id": "...",
    "address": "...",
    "effective_date": "...",
    "authorized_signatory": "...",
    "document_type_detected": "...",
    "key_clauses_or_notes": "..."
  }},
  "confidence_score": 0.95,
  "validation_flags": ["list any missing required fields or suspicious inconsistencies"],
  "raw_summary": "Brief 1-2 sentence executive summary of document"
}}
"""
        try:
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            content_text = response.content[0].text
            # Parse JSON safely
            match = re.search(r'\{.*\}', content_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                data["provider"] = "anthropic_claude"
                return data
            else:
                return MockClaudeExtractorAdapter().extract_document(raw_text, file_name, document_type_hint)
        except Exception as exc:
            logger.error("Error calling Anthropic API: %s. Falling back to mock extractor.", exc)
            fallback = MockClaudeExtractorAdapter().extract_document(raw_text, file_name, document_type_hint)
            fallback["validation_flags"].append(f"AI API error: {str(exc)}")
            return fallback


# ==============================================================================
# FACTORY / GETTERS
# ==============================================================================

def get_email_adapter() -> EmailAdapterInterface:
    return MockEmailAdapter()

def get_storage_adapter() -> StorageAdapterInterface:
    return MockStorageAdapter()

def get_crm_adapter() -> CRMAdapterInterface:
    return MockCRMAdapter()

def get_task_adapter() -> ProjectTaskAdapterInterface:
    return MockProjectTaskAdapter()

def get_document_extractor_adapter() -> DocumentExtractorInterface:
    choice = getattr(settings, 'AI_EXTRACTOR_ADAPTER', 'mock')
    if choice == 'claude' and getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return AnthropicClaudeAdapter()
    return MockClaudeExtractorAdapter()
