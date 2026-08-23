# ─── base_text_interface.py ───

from abc import abstractmethod

from .base_document_interface import BaseDocumentInterface


class BaseTextInterface(BaseDocumentInterface):
    """Abstract base for text processing engines."""

    def _validate_text(self, text: str) -> None:
        """Validate that the text is not empty."""
        if not text or not text.strip():
            raise ValueError("Received empty text.")

    @abstractmethod
    async def extract_text(self, text: str) -> str:
        """Process and extract text from raw string input."""
        ...