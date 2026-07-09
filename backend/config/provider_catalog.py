"""Provider catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransportType = Literal["openai_chat", "anthropic_messages"]

DEEPSEEK_ANTHROPIC_DEFAULT_BASE = "https://api.deepseek.com/anthropic"
DEEPSEEK_DEFAULT_BASE = DEEPSEEK_ANTHROPIC_DEFAULT_BASE
MINIMAX_DEFAULT_BASE = "https://api.minimaxi.com/anthropic"
GLM_DEFAULT_BASE = "https://cn.morbuke.com"


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    transport_type: TransportType
    capabilities: tuple[str, ...]
    credential_env: str | None = None
    credential_url: str | None = None
    credential_attr: str | None = None
    static_credential: str | None = None
    default_base_url: str | None = None
    base_url_attr: str | None = None
    proxy_attr: str | None = None


PROVIDER_CATALOG: dict[str, ProviderDescriptor] = {
    "deepseek": ProviderDescriptor(
        provider_id="deepseek",
        transport_type="anthropic_messages",
        credential_env="DEEPSEEK_API_KEY",
        credential_url="https://platform.deepseek.com/api_keys",
        credential_attr="deepseek_api_key",
        default_base_url=DEEPSEEK_ANTHROPIC_DEFAULT_BASE,
        capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
    ),
    "minimax": ProviderDescriptor(
        provider_id="minimax",
        transport_type="anthropic_messages",
        credential_env="MINIMAX_API_KEY",
        credential_url=(
            "https://platform.minimaxi.com/user-center/basic-information/interface-key"
        ),
        credential_attr="minimax_api_key",
        default_base_url=MINIMAX_DEFAULT_BASE,
        capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
    ),
    "glm": ProviderDescriptor(
        provider_id="glm",
        transport_type="anthropic_messages",
        credential_env="GLM_API_KEY",
        credential_url=None,
        credential_attr="glm_api_key",
        default_base_url=GLM_DEFAULT_BASE,
        capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
    ),
}

SUPPORTED_PROVIDER_IDS: tuple[str, ...] = tuple(PROVIDER_CATALOG.keys())
