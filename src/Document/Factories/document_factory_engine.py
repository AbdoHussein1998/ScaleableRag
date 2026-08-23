# ─── document_factory_engine.py ───

from typing import Optional

from .base_document_interface import BaseDocumentInterface
from ..Engines.pdf_plumber_engine import PdfPlumberEngine
from ..Engines.pdf_mupdf_engine import PdfMuPdfEngine
from ..Engines.text_processing_engine import TextProcessingEngine


# Registry of available engines
ENGINE_REGISTRY = {
    "pdfplumber": PdfPlumberEngine,
    "pymupdf": PdfMuPdfEngine,
    "text_processing": TextProcessingEngine,
}


class DocumentFactoryEngine:
    """Factory that selects and initializes any document engine."""

    @staticmethod
    async def select_engine(
        engine_name: str, logger_instance: Optional = None
    ) -> BaseDocumentInterface:
        """
        Returns a ready-to-use engine instance.

        Args:
            engine_name: "pdfplumber" | "pymupdf" | "text_processing"
            logger_instance: Optional loguru logger.

        Returns:
            An initialized BaseDocumentInterface instance.

        Raises:
            ValueError: If engine_name is not supported.
        """
        engine_class = ENGINE_REGISTRY.get(engine_name.lower())

        if engine_class is None:
            supported = ", ".join(ENGINE_REGISTRY.keys())
            raise ValueError(
                f"Unsupported engine: '{engine_name}'. "
                f"Supported engines: {supported}"
            )

        instance = await engine_class.init_class(logger_instance=logger_instance)
        return instance