# ─── Engines/pdf_mupdf_engine.py ───

from typing import Optional, List

import fitz  # PyMuPDF

from ..Factories.base_pdf_interface import BasePdfInterface


class PdfMuPdfEngine(BasePdfInterface):
    """PyMuPDF (fitz) implementation."""

    @classmethod
    async def init_class(cls, logger_instance: Optional = None) -> "PdfMuPdfEngine":
        """Async factory — returns a ready-to-use PdfMuPdfEngine instance."""
        instance = await super().init_class(logger_instance=logger_instance)
        return instance

    def _process_document(self, doc: fitz.Document) -> List[str]:
        """Process all pages from an open fitz Document."""
        all_text: List[str] = []

        try:
            for page_num, page in enumerate(doc, start=1):
                try:
                    text = page.get_text("text")

                    if text and text.strip():
                        all_text.append(text)
                        self._logger.debug(
                            f"Page {page_num}: extracted {len(text)} chars."
                        )
                    else:
                        self._logger.debug(f"Page {page_num}: no text found.")

                except Exception as e:
                    self._logger.warning(
                        f"Page {page_num}: extraction failed — {e}"
                    )
        finally:
            doc.close()

        return all_text

    async def extract_text_from_path(self, file_path: str) -> List[str]:
        """
        Extract text from a PDF file on disk using PyMuPDF.

        Args:
            file_path: Path to the PDF file.

        Returns:
            List of extracted text strings, one per page.
        """
        self._ensure_initialized()
        self._validate_file_path(file_path)


        self._logger.info(f"[PyMuPDF] Extracting text from path: {file_path}")
        try:
            doc = fitz.open(file_path)
            result = self._process_document(doc)

            self._logger.success(f"[PyMuPDF] Extraction complete. {len(result)} page(s) from path.")
            return result

        except Exception as e:
            self._logger.error(f"[PyMuPDF] Extraction from path failed: {e}")
            raise

    async def extract_text_from_bytes(
        self, file_bytes: bytes, filename: Optional[str] = None
    ) -> List[str]:
        """
        Extract text from raw PDF bytes using PyMuPDF.

        Args:
            file_bytes: Raw bytes of the PDF file.
            filename: Optional original filename for logging.

        Returns:
            List of extracted text strings, one per page.
        """
        self._ensure_initialized()
        self._validate_file_bytes(file_bytes)

        display_name = filename or "uploaded_payload"
        self._logger.info(f"[PyMuPDF] Extracting text from bytes: {display_name}")

        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            result = self._process_document(doc)

            self._logger.success(
                f"[PyMuPDF] Extraction complete. "
                f"{len(result)} page(s) from bytes ({display_name})."
            )
            return result

        except Exception as e:
            self._logger.error(
                f"[PyMuPDF] Extraction from bytes failed ({display_name}): {e}"
            )
            raise