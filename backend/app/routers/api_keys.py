from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.exceptions import AppException
from app.models.provider import Provider
from app.models.user import User
from app.schemas.api_key import (
    CreateKeyRequest,
    CreateKeyResponse,
    KeyResponse,
    UpdateKeyRequest,
)
from app.schemas.common import ErrorResponse
from app.services.api_key_service import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    update_api_key,
)

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post(
    "",
    response_model=CreateKeyResponse,
    status_code=201,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
        400: {"model": ErrorResponse, "description": "Channel not available"},
    },
)
async def create_key(
    body: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate the chosen channel
    p = await db.execute(select(Provider).where(Provider.id == body.channel_id))
    provider = p.scalar_one_or_none()
    if not provider or provider.status != "active":
        raise AppException(status_code=400, error="选择的渠道不可用", code="CHANNEL_UNAVAILABLE")

    api_key, raw_key = await create_api_key(
        db, user=user, name=body.name, channel_id=body.channel_id
    )
    return {
        "id": api_key.id,
        "name": api_key.name,
        "keyPrefix": api_key.key_prefix,
        "rawKey": raw_key,
        "status": api_key.status,
        "channelId": api_key.channel_id,
        "channelName": provider.channel_name,
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

    # Bulk-fetch provider names in one query
    provider_ids = {k.channel_id for k in keys if k.channel_id is not None}
    name_by_id: dict[int, str] = {}
    if provider_ids:
        rows = await db.execute(
            select(Provider.id, Provider.channel_name).where(Provider.id.in_(provider_ids))
        )
        name_by_id = {pid: cname for pid, cname in rows.all()}

    return [
        {
            "id": k.id,
            "name": k.name,
            "keyPrefix": k.key_prefix,
            "status": k.status,
            "createdAt": k.created_at,
            "lastUsedAt": k.last_used_at,
            "channelId": k.channel_id,
            "channelName": name_by_id.get(k.channel_id) if k.channel_id else None,
        }
        for k in keys
    ]


@router.patch(
    "/{key_id}",
    response_model=KeyResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Key not found"},
        400: {"model": ErrorResponse, "description": "Key revoked or channel unavailable"},
    },
)
async def update_key(
    key_id: int,
    body: UpdateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    api_key = await update_api_key(db, user=user, key_id=key_id, channel_id=body.channel_id)
    channel_name = None
    if api_key.channel_id is not None:
        p = await db.execute(select(Provider).where(Provider.id == api_key.channel_id))
        provider = p.scalar_one_or_none()
        channel_name = provider.channel_name if provider else None
    return {
        "id": api_key.id,
        "name": api_key.name,
        "keyPrefix": api_key.key_prefix,
        "status": api_key.status,
        "createdAt": api_key.created_at,
        "lastUsedAt": api_key.last_used_at,
        "channelId": api_key.channel_id,
        "channelName": channel_name,
    }


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
