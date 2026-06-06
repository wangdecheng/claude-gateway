"""Application exception classes — shared across all modules without circular imports."""


class AppException(Exception):
    """Custom application exception with error code.

    Raised by services to signal expected error conditions.
    Caught by the FastAPI exception handler in app.main for uniform JSON responses.
    """

    def __init__(self, status_code: int, error: str, code: str):
        self.status_code = status_code
        self.error = error
        self.code = code
