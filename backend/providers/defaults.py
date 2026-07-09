"""Re-export default upstream base URLs from the config provider catalog."""

from config.provider_catalog import (
    DEEPSEEK_ANTHROPIC_DEFAULT_BASE,
    DEEPSEEK_DEFAULT_BASE,
    GLM_DEFAULT_BASE,
    MINIMAX_DEFAULT_BASE,
)

__all__ = (
    "DEEPSEEK_ANTHROPIC_DEFAULT_BASE",
    "DEEPSEEK_DEFAULT_BASE",
    "GLM_DEFAULT_BASE",
    "MINIMAX_DEFAULT_BASE",
)
