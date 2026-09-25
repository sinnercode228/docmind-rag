"""Typed application errors. The API layer maps them to HTTP responses in one place."""

from __future__ import annotations


class DocMindError(Exception):
    """Base class for expected, user-facing errors."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DocMindError):
    status_code = 404
    code = "not_found"


class UnsupportedDocumentError(DocMindError):
    status_code = 415
    code = "unsupported_document"


class DocumentTooLargeError(DocMindError):
    status_code = 413
    code = "document_too_large"


class UnsafeURLError(DocMindError):
    status_code = 422
    code = "unsafe_url"


class ExtractionError(DocMindError):
    status_code = 422
    code = "extraction_failed"


class ProviderError(DocMindError):
    """An upstream LLM / embedding provider failed."""

    status_code = 502
    code = "provider_error"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
