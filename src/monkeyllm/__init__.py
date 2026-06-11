"""MonkeyLLM — agent-navigable knowledge forest (Phase 0: Vine)."""

from monkeyllm.errors import VineError
from monkeyllm.vine import Vine

__version__ = "0.1.0"
__all__ = ["Vine", "VineError", "__version__"]
