"""FastAPI route handlers — adapted for DB-backed auth + billing."""

from fastapi import APIRouter, Depends, Request, Response

from config.settings import Settings
from core.anthropic import get_token_count

from .dependencies import get_settings, require_api_key
from .models.anthropic import TokenCountRequest
from .models.responses import ModelResponse, ModelsListResponse
from .services import ClaudeProxyService

router = APIRouter()


def get_proxy_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ClaudeProxyService:
    """Build the proxy service for route handlers (provider resolved per-request from DB)."""
    return ClaudeProxyService(
        settings,
        provider_getter=lambda provider_type: _resolve_provider_for_request(request, provider_type),
        token_counter=get_token_count,
    )


def _resolve_provider_for_request(request: Request, provider_type: str):
    """Resolve provider from app registry (populated by proxy endpoint)."""
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        from providers.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError("Provider registry not configured")
    # The proxy endpoint stores the active provider on request.state
    provider = getattr(request.state, "active_provider", None)
    if provider is not None:
        return provider
    # Fallback: try to get from registry with empty key (will fail for real calls)
    try:
        return reg.get(provider_type, api_key="")
    except Exception:
        from providers.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError(f"Provider {provider_type} not available")


# =============================================================================
# Routes
# =============================================================================
@router.api_route("/v1/messages", methods=["HEAD", "OPTIONS"])
async def probe_messages(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes."""
    return Response(status_code=204, headers={"Allow": "POST, HEAD, OPTIONS"})


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request_data: TokenCountRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Count tokens for a request."""
    return service.count_tokens(request_data)


@router.api_route("/v1/messages/count_tokens", methods=["HEAD", "OPTIONS"])
async def probe_count_tokens(_auth=Depends(require_api_key)):
    return Response(status_code=204, headers={"Allow": "POST, HEAD, OPTIONS"})


@router.get("/v1/models")
async def list_models(
    request: Request,
    _auth=Depends(require_api_key),
):
    """List models from database."""
    from sqlalchemy import select

    from app.models.model import Model

    session_factory = request.app.state.db_session_factory
    async with session_factory() as db:
        result = await db.execute(select(Model).where(Model.status == "active"))
        models = result.scalars().all()
        data = [
            ModelResponse(
                id=m.public_name,
                display_name=m.public_name,
                created_at=m.created_at.isoformat() if m.created_at else "2024-01-01T00:00:00Z",
            )
            for m in models
        ]
        return ModelsListResponse(
            data=data,
            first_id=data[0].id if data else None,
            has_more=False,
            last_id=data[-1].id if data else None,
        )


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.api_route("/health", methods=["HEAD", "OPTIONS"])
async def probe_health():
    return Response(status_code=204, headers={"Allow": "GET, HEAD, OPTIONS"})


@router.get("/api/public-url")
async def get_public_url(settings: Settings = Depends(get_settings)):
    """Return the gateway's public base URL for client configuration."""
    return {"baseUrl": settings.public_url}


@router.get("/")
async def root(settings: Settings = Depends(get_settings), _auth=Depends(require_api_key)):
    return {"status": "ok", "provider": settings.provider_type, "model": settings.model_name}


@router.api_route("/", methods=["HEAD", "OPTIONS"])
async def probe_root():
    return Response(status_code=204, headers={"Allow": "GET, HEAD, OPTIONS"})
