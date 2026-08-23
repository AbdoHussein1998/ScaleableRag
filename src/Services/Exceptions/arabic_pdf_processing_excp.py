# arabic_pdf_processing_excp.py


class ArabicPdfProcessingError(Exception):
    """
    Custom exception for all PDF processing service errors.
    Used across the entire ArabicPdfProcessingService.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

