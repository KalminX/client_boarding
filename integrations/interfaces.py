from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class EmailAdapterInterface(ABC):
    @abstractmethod
    def send_email(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        recipient_name: str = "",
        body_html: str = "",
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sends an email and returns delivery metadata (e.g. message_id, status)."""
        pass


class StorageAdapterInterface(ABC):
    @abstractmethod
    def create_client_folder(self, client_name: str, case_id: str) -> Dict[str, Any]:
        """Creates a storage folder for the client onboarding case and returns folder_id and folder_url."""
        pass


class CRMAdapterInterface(ABC):
    @abstractmethod
    def create_or_update_company_and_deal(
        self,
        company_name: str,
        contact_name: str,
        email: str,
        contract_value: float,
        case_id: str
    ) -> Dict[str, Any]:
        """Creates or updates CRM company, contact, and deal records and returns crm_id and crm_url."""
        pass


class ProjectTaskAdapterInterface(ABC):
    @abstractmethod
    def create_onboarding_project(
        self,
        company_name: str,
        case_id: str,
        tasks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Creates project board and initial onboarding tasks and returns project_board_id and project_board_url."""
        pass


class DocumentExtractorInterface(ABC):
    @abstractmethod
    def extract_document(
        self,
        raw_text: str,
        file_name: str,
        document_type_hint: str = "general"
    ) -> Dict[str, Any]:
        """
        Extracts structured key-value information from raw text or document content.
        Returns a dict containing:
        - extracted_fields: dict
        - confidence_score: float (0.0 to 1.0)
        - validation_flags: list of string warnings/missing fields
        - raw_summary: str
        """
        pass
