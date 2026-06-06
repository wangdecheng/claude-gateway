"""Admin user management schemas."""

from pydantic import BaseModel, Field


class AdminUserResponse(BaseModel):
    """User entry for the admin user list."""

    id: int
    email: str
    balance: int
    role: str
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}
