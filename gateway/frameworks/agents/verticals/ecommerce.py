from ..base import BaseAgent


class EcommerceAgent(BaseAgent):
    """E-commerce vertical agent — see saas.py's docstring for why
    SYSTEM_PROMPT_ADDITIONS starts empty (nothing real was ever authored
    in the prior database-row version)."""

    VERTICAL = "ecommerce"
    SYSTEM_PROMPT_ADDITIONS = ""
