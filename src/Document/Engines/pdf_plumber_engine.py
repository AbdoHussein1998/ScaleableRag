# ─── Engines/pdf_plumber_engine.py ───

import io
from typing import Optional, List

import pdfplumber
import arabic_reshaper
from bidi.algorithm import get_display

from ..Factories.base_pdf_interface import BasePdfInterface


class PdfPlumberEngine(BasePdfInterface):
    """pdfplumber implementation — includes Arabic RTL fix."""

    @classmethod
    async def init_class(cls, logger_instance: Optional = None) -> "PdfPlumberEngine":
        """Async factory — returns a ready-to-use PdfPlumberEngine instance."""
        instance = await super().init_class(logger_instance=logger_instance)
        return instance

    @staticmethod
    def fix_arabic_text(text: Optional[str]) -> str:
        """
        Fix Arabic RTL extracted text from pdfplumber.

        Args:
            text: Raw extracted text (possibly garbled RTL).

        Returns:
            Corrected display-order Arabic text.
        """
        if not text:
            return ""

        reshaped_text = arabic_reshaper.reshape(text)
        corrected_text = get_display(reshaped_text)
        return corrected_text

    def _process_pages(self, pdf: pdfplumber.PDF) -> List[str]:
        """Process all pages from an open pdfplumber PDF object."""
        all_text: List[str] = []

        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text()

                if text and text.strip():
                    fixed_text = self.fix_arabic_text(text)
                    all_text.append(fixed_text)
                    self._logger.debug(
                        f"Page {page_num}: extracted {len(fixed_text)} chars."
                    )
                else:
                    self._logger.debug(f"Page {page_num}: no text found.")

            except Exception as e:
                self._logger.warning(f"Page {page_num}: extraction failed — {e}")

        return all_text

    async def extract_text_from_path(self, file_path: str) -> List[str]:
        """
        Extract text from a PDF file on disk using pdfplumber.

        Args:
            file_path: Path to the PDF file.

        Returns:
            List of extracted text strings, one per page.
        """
        self._ensure_initialized()
        self._validate_file_path(file_path)

        self._logger.info(f"[PdfPlumber] Extracting text from path: {file_path}")

        try:
            with pdfplumber.open(file_path) as pdf:
                result = self._process_pages(pdf)

            self._logger.success(
                f"[PdfPlumber] Extraction complete. {len(result)} page(s) from path."
            )
            return result

        except Exception as e:
            self._logger.error(f"[PdfPlumber] Extraction from path failed: {e}")
            raise

    async def extract_text_from_bytes(self, file_bytes: bytes, filename: Optional[str] = None) -> List[str]:
        """
        Extract text from raw PDF bytes using pdfplumber.

        Args:
            file_bytes: Raw bytes of the PDF file.
            filename: Optional original filename for logging.

        Returns:
            List of extracted text strings, one per page.
        """
        self._ensure_initialized()
        self._validate_file_bytes(file_bytes)

        display_name = filename or "uploaded_payload"
        self._logger.info(f"[PdfPlumber] Extracting text from bytes: {display_name}")

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                result = self._process_pages(pdf)

            self._logger.success(
                f"[PdfPlumber] Extraction complete. "
                f"{len(result)} page(s) from bytes ({display_name})."
            )
            return result

        except Exception as e:
            self._logger.error(
                f"[PdfPlumber] Extraction from bytes failed ({display_name}): {e}"
            )
            raise