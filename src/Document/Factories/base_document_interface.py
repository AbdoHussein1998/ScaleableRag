# ─── base_document_interface.py ───

from abc import ABC
from typing import Optional
from loguru import logger


class BaseDocumentInterface(ABC):
    """Abstract base for all document processing implementations (PDF, Text, etc.)."""

    def __init__(self, logger_instance: Optional = None):
        self._logger = logger_instance or logger
        self._initialized = False

    @classmethod
    async def init_class(cls, logger_instance: Optional = None) -> "BaseDocumentInterface":
        """Async factory — returns a ready-to-use instance."""
        active_logger = logger_instance or logger
        instance = cls(logger_instance=active_logger)
        instance._initialized = True
        active_logger.info(f"{cls.__name__} initialized successfully.")
        return instance

    def _ensure_initialized(self) -> None:
        """Guard to ensure the instance was created via init_class."""
        if not self._initialized:
            raise RuntimeError(
                f"{self.__class__.__name__} was not initialized properly. "
                f"Use 'await {self.__class__.__name__}.init_class()' to create an instance."
            )