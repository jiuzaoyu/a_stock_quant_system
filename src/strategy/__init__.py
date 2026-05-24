from .base import BaseStrategy
from .cta import CTAStrategy
from .multi_factor import MultiFactorStrategy

# 简洁别名，便于 from src.strategy import CTA
CTA = CTAStrategy

__all__ = [
    "BaseStrategy",
    "CTAStrategy",
    "CTA",
    "MultiFactorStrategy",
]
