"""Provider import smoke tests for the runtime Python version."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_deepseek_provider_imports():
    from providers.deepseek import DeepSeekProvider

    assert DeepSeekProvider is not None


def test_minimax_provider_imports():
    from providers.minimax import MiniMaxProvider

    assert MiniMaxProvider is not None
