"""Provider registry wiring tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.provider_catalog import PROVIDER_CATALOG, SUPPORTED_PROVIDER_IDS
from config.settings import Settings
from providers.registry import PROVIDER_FACTORIES, create_provider


def test_provider_catalog_and_factories_include_minimax():
    assert "minimax" in PROVIDER_CATALOG
    assert "minimax" in SUPPORTED_PROVIDER_IDS
    assert "minimax" in PROVIDER_FACTORIES


def test_create_minimax_provider_from_registry():
    from providers.minimax import MiniMaxProvider

    settings = Settings(
        _env_file=None,
        MINIMAX_CACHE_CREATION_MAX_INPUT_MULTIPLIER=7,
        LOG_MINIMAX_USAGE=True,
    )

    provider = create_provider(
        "minimax",
        api_key="test-key",
        base_url="https://api.minimaxi.com/anthropic",
        settings=settings,
    )

    assert isinstance(provider, MiniMaxProvider)
    assert provider._cache_creation_max_input_multiplier == 7
    assert provider._config.log_minimax_usage is True


def test_provider_catalog_and_factories_include_xunfei():
    assert "xunfei" in PROVIDER_CATALOG
    assert "xunfei" in SUPPORTED_PROVIDER_IDS
    assert "xunfei" in PROVIDER_FACTORIES


def test_create_xunfei_provider_from_registry():
    from providers.xunfei import XunfeiProvider

    settings = Settings(
        _env_file=None,
        XUNFEI_CACHE_CREATION_MAX_INPUT_MULTIPLIER=7,
        LOG_XUNFEI_USAGE=True,
    )

    provider = create_provider(
        "xunfei",
        api_key="test-key",
        base_url="https://cn.morbuke.com",
        settings=settings,
    )

    assert isinstance(provider, XunfeiProvider)
    assert provider._cache_creation_max_input_multiplier == 7
    assert provider._config.log_xunfei_usage is True
