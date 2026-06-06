from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.api_key import CreateKeyRequest, CreateKeyResponse, KeyResponse
from app.schemas.common import ErrorResponse
from app.services.api_key_service import create_api_key, list_api_keys, revoke_api_key

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post(
    "",
    response_model=CreateKeyResponse,
    status_code=201,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def create_key(
    body: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    api_key, raw_key = await create_api_key(db, user=user, name=body.name)
    return {
        "id": api_key.id,
        "name": api_key.name,
        "keyPrefix": api_key.key_prefix,
        "rawKey": raw_key,
        "status": api_key.status,
        "createdAt": api_key.created_at,
    }


@router.get(
    "",
    response_model=list[KeyResponse],
)
async def list_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    keys = await list_api_keys(db, user=user)
    return [
        {
            "id": k.id,
            "name": k.name,
            "keyPrefix": k.key_prefix,
            "status": k.status,
            "createdAt": k.created_at,
            "lastUsedAt": k.last_used_at,
        }
        for k in keys
    ]


@router.delete(
    "/{key_id}",
    responses={
        404: {"model": ErrorResponse, "description": "Key not found"},
        400: {"model": ErrorResponse, "description": "Key already revoked"},
    },
)
async def revoke_key(
    key_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await revoke_api_key(db, user=user, key_id=key_id)
    return {"message": "密钥已撤销"}
