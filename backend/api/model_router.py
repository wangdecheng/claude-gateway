"""Model routing — resolves incoming model names to DB-backed provider/model pairs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config.settings import Settings

from .gateway_model_ids import decode_gateway_model_id
from .models.anthropic import MessagesRequest, TokenCountRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    original_model: str
    provider_id: str
    provider_model: str
    provider_model_ref: str
    thinking_enabled: bool
    # DB references for billing
    db_model_id: int | None = None
    db_provider_id: int | None = None
    db_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class RoutedMessagesRequest:
    request: MessagesRequest
    resolved: ResolvedModel


@dataclass(frozen=True, slots=True)
class RoutedTokenCountRequest:
    request: TokenCountRequest
    resolved: ResolvedModel


class ModelRouter:
    """Resolve incoming model names using DB lookup with settings fallback."""

    def __init__(self, settings: Settings, db: "AsyncSession | None" = None):
        self._settings = settings
        self._db = db

    def resolve(self, claude_model_name: str) -> ResolvedModel:
        """Resolve a model name. Uses settings-based fallback when no DB is available."""
        direct = self._direct_provider_model(claude_model_name)
        if direct[0] is not None:
            return ResolvedModel(
                original_model=claude_model_name,
                provider_id=direct[0],
                provider_model=direct[1],  # type: ignore[arg-type]
                provider_model_ref=claude_model_name,
                thinking_enabled=direct[2]
                if direct[2] is not None
                else self._settings.enable_model_thinking,
            )

        provider_model_ref = self._settings.model
        thinking_enabled = self._settings.enable_model_thinking
        provider_id = Settings.parse_provider_type(provider_model_ref)
        provider_model = Settings.parse_model_name(provider_model_ref)
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=provider_id,
            provider_model=provider_model,
            provider_model_ref=provider_model_ref,
            thinking_enabled=thinking_enabled,
        )

    async def resolve_from_db(self, model_name: str) -> ResolvedModel:
        """Resolve a model name using the database (model → channel → provider)."""
        if self._db is None:
            return self.resolve(model_name)

        from sqlalchemy import select

        # Import models lazily to avoid circular imports
        from app.models.model import ChannelConfig, Model
        from app.models.provider import Provider

        # 1. Look up model by public_name
        result = await self._db.execute(
            select(Model).where(Model.public_name == model_name, Model.status == "active")
        )
        model = result.scalar_one_or_none()

        if model is None:
            # Fall back to settings-based resolution
            return self.resolve(model_name)

        # 2. Look up default channel (or lowest-multiplier fallback)
        result = await self._db.execute(
            select(ChannelConfig).where(
                ChannelConfig.model_id == model.id,
                ChannelConfig.status == "active",
                ChannelConfig.is_default == True,
            )
        )
        channel = result.scalar_one_or_none()

        if channel is None:
            # Fallback: lowest multiplier active channel
            result = await self._db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.model_id == model.id,
                    ChannelConfig.status == "active",
                ).order_by(ChannelConfig.multiplier.asc()).limit(1)
            )
            channel = result.scalar_one_or_none()

        if channel is None:
            return self.resolve(model_name)

        # 3. Look up provider
        result = await self._db.execute(
            select(Provider).where(
                Provider.id == channel.provider_id,
                Provider.status == "active",
            )
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return self.resolve(model_name)

        return ResolvedModel(
            original_model=model_name,
            provider_id=provider.name,
            provider_model=channel.provider_model_id,
            provider_model_ref=f"{provider.name}/{channel.provider_model_id}",
            thinking_enabled=self._settings.enable_model_thinking,
            db_model_id=model.id,
            db_provider_id=provider.id,
            db_channel_id=channel.id,
        )

    def _direct_provider_model(self, model_name: str) -> tuple[str | None, str | None, bool | None]:
        decoded = decode_gateway_model_id(model_name)
        if decoded is not None:
            from config.provider_ids import SUPPORTED_PROVIDER_IDS

            if decoded.provider_id not in SUPPORTED_PROVIDER_IDS:
                return None, None, None
            return decoded.provider_id, decoded.provider_model, decoded.force_thinking_enabled

        provider_id, separator, provider_model = model_name.partition("/")
        if not separator:
            return None, None, None
        from config.provider_ids import SUPPORTED_PROVIDER_IDS

        if provider_id not in SUPPORTED_PROVIDER_IDS:
            return None, None, None
        if not provider_model:
            return None, None, None
        return provider_id, provider_model, None

    def resolve_messages_request(self, request: MessagesRequest) -> RoutedMessagesRequest:
        resolved = self.resolve(request.model)
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(request=routed, resolved=resolved)

    def resolve_token_count_request(self, request: TokenCountRequest) -> RoutedTokenCountRequest:
        resolved = self.resolve(request.model)
        routed = request.model_copy(update={"model": resolved.provider_model}, deep=True)
        return RoutedTokenCountRequest(request=routed, resolved=resolved)
