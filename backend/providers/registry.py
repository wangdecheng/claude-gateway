"""Provider registry for DB-backed provider config."""

from __future__ import annotations

from config.provider_catalog import PROVIDER_CATALOG, ProviderDescriptor
from config.settings import Settings
from providers.base import BaseProvider, ProviderConfig
from providers.exceptions import UnknownProviderTypeError

ProviderFactory = type(lambda config, settings: None)  # type placeholder

PROVIDER_DESCRIPTORS: dict[str, ProviderDescriptor] = PROVIDER_CATALOG


def _create_deepseek(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.deepseek import DeepSeekProvider

    return DeepSeekProvider(
        config,
        cache_creation_max_input_multiplier=settings.deepseek_cache_creation_max_input_multiplier,
    )


def _create_minimax(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.minimax import MiniMaxProvider

    return MiniMaxProvider(
        config,
        cache_creation_max_input_multiplier=settings.minimax_cache_creation_max_input_multiplier,
    )


def _create_glm(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.glm import GlmProvider

    return GlmProvider(
        config,
        cache_creation_max_input_multiplier=settings.glm_cache_creation_max_input_multiplier,
    )


def _create_volcengine(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.volcengine import VolcengineProvider

    return VolcengineProvider(
        config,
        cache_creation_max_input_multiplier=(
            settings.volcengine_cache_creation_max_input_multiplier
        ),
    )


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "deepseek": _create_deepseek,
    "minimax": _create_minimax,
    "glm": _create_glm,
    "volcengine": _create_volcengine,
}


def build_provider_config(
    descriptor: ProviderDescriptor,
    *,
    api_key: str,
    base_url: str | None = None,
    settings: Settings | None = None,
) -> ProviderConfig:
    """Build a ProviderConfig from a descriptor and an explicit API key (from DB key pool)."""
    s = settings or Settings()
    return ProviderConfig(
        api_key=api_key,
        base_url=base_url or descriptor.default_base_url,
        rate_limit=s.provider_rate_limit,
        rate_window=s.provider_rate_window,
        max_concurrency=s.provider_max_concurrency,
        http_read_timeout=s.http_read_timeout,
        http_write_timeout=s.http_write_timeout,
        http_connect_timeout=s.http_connect_timeout,
        enable_thinking=s.enable_model_thinking,
        proxy="",
        log_raw_sse_events=s.log_raw_sse_events,
        log_deepseek_usage=s.log_deepseek_usage,
        log_minimax_usage=s.log_minimax_usage,
        log_glm_usage=s.log_glm_usage,
        log_volcengine_usage=s.log_volcengine_usage,
        log_api_error_tracebacks=s.log_api_error_tracebacks,
    )


def create_provider(
    provider_id: str,
    *,
    api_key: str,
    base_url: str | None = None,
    settings: Settings | None = None,
) -> BaseProvider:
    """Create a provider instance with an explicit API key (from DB)."""
    s = settings or Settings()
    descriptor = PROVIDER_DESCRIPTORS.get(provider_id)
    if descriptor is None:
        supported = "', '".join(PROVIDER_DESCRIPTORS)
        raise UnknownProviderTypeError(
            f"Unknown provider_type: '{provider_id}'. Supported: '{supported}'"
        )
    config = build_provider_config(descriptor, api_key=api_key, base_url=base_url, settings=s)
    factory = PROVIDER_FACTORIES.get(provider_id)
    if factory is None:
        raise AssertionError(f"Unhandled provider descriptor: {provider_id}")
    return factory(config, s)


class ProviderRegistry:
    """Cache provider instances by a compound key (provider_id, api_key_hash)."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._providers: dict[str, BaseProvider] = {}

    def get(self, provider_id: str, *, api_key: str, base_url: str | None = None) -> BaseProvider:
        """Get or create a provider for the given id + api_key combination."""
        import hashlib

        cache_key = f"{provider_id}:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        if cache_key not in self._providers:
            self._providers[cache_key] = create_provider(
                provider_id, api_key=api_key, base_url=base_url, settings=self._settings
            )
        return self._providers[cache_key]

    async def cleanup(self) -> None:
        for provider in self._providers.values():
            await provider.cleanup()
        self._providers.clear()
