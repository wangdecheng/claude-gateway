"""Re-exports default upstream base URLs from the config provider catalog — Phase 1: DeepSeek only."""

from config.provider_catalog import (
    DEEPSEEK_ANTHROPIC_DEFAULT_BASE,
    DEEPSEEK_DEFAULT_BASE,
)

__all__ = (
    "DEEPSEEK_ANTHROPIC_DEFAULT_BASE",
    "DEEPSEEK_DEFAULT_BASE",
)
