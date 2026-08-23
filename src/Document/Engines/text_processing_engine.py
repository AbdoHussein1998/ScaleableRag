# ─── Engines/text_processing_engine.py ───

from typing import Optional

from ..Factories.base_text_interface import BaseTextInterface


class TextProcessingEngine(BaseTextInterface):
    """Text processing implementation for raw string input."""

    @classmethod
    async def init_class(cls, logger_instance: Optional = None) -> "TextProcessingEngine":
        """Async factory — returns a ready-to-use TextProcessingEngine instance."""
        instance = await super().init_class(logger_instance=logger_instance)
        return instance

    async def extract_text(self, text: str) -> str:
        """
        Process and extract text from raw string input.

        Args:
            text: Raw text string (e.g., from FastAPI payload).

        Returns:
            Cleaned/processed text string.
        """
        self._ensure_initialized()
        self._validate_text(text)

        self._logger.info("[TextProcessing] Processing text input...")

        try:
            result = text.strip()

            self._logger.success(
                f"[TextProcessing] Processing complete. {len(result)} chars."
            )
            return result

        except Exception as e:
            self._logger.error(f"[TextProcessing] Processing failed: {e}")
            raise