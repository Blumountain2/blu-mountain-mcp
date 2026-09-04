from ..base import BaseAgent


class TransactionalAgent(BaseAgent):
    """Transactional vertical agent — see saas.py's docstring for why
    SYSTEM_PROMPT_ADDITIONS starts empty (nothing real was ever authored
    in the prior database-row version)."""

    VERTICAL = "transactional"
    SYSTEM_PROMPT_ADDITIONS = ""
