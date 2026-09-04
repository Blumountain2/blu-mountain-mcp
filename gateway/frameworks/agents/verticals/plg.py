from ..base import BaseAgent


class PLGAgent(BaseAgent):
    """PLG vertical agent — see saas.py's docstring for why
    SYSTEM_PROMPT_ADDITIONS starts empty (nothing real was ever authored
    in the prior database-row version)."""

    VERTICAL = "plg"
    SYSTEM_PROMPT_ADDITIONS = ""
