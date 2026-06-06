from typing import Optional

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: Optional[str] = None
