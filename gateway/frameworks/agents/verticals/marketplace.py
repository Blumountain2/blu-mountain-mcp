from ..base import BaseAgent


class MarketplaceAgent(BaseAgent):
    """Marketplace vertical agent — see saas.py's docstring for why
    SYSTEM_PROMPT_ADDITIONS starts empty (nothing real was ever authored
    in the prior database-row version)."""

    VERTICAL = "marketplace"
    SYSTEM_PROMPT_ADDITIONS = ""
