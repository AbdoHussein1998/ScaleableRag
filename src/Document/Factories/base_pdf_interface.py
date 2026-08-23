# ─── base_pdf_interface.py ───

from abc import abstractmethod
from typing import Optional, List
import os

from .base_document_interface import BaseDocumentInterface


class BasePdfInterface(BaseDocumentInterface):
    """Abstract base for PDF engines specifically."""

    def _validate_file_path(self, file_path: str) -> None:
        """Validate that the file exists and is a PDF."""
        if not file_path:
            raise ValueError("File path cannot be empty.")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        if not file_path.lower().endswith(".pdf"):
            raise ValueError(f"File is not a PDF: {file_path}")

    def _validate_file_bytes(self, file_bytes: bytes) -> None:
        """Validate that the bytes are not empty."""
        if not file_bytes:
            raise ValueError("Received empty file bytes.")

    @abstractmethod
    async def extract_text_from_path(self, file_path: str) -> List[str]:
        """Extract text from a PDF file on disk."""
        ...

    @abstractmethod
    async def extract_text_from_bytes(self, file_bytes: bytes, filename: Optional[str] = None) -> List[str]:
        """Extract text from raw PDF bytes (e.g., FastAPI UploadFile)."""
        ...


