from ..base import BaseAgent


class ServicesProjectAgent(BaseAgent):
    """Services/Project vertical agent — see saas.py's docstring for why
    SYSTEM_PROMPT_ADDITIONS starts empty (nothing real was ever authored
    in the prior database-row version).

    VERTICAL is "services-project" (hyphenated) — matches
    frameworks.ingest.FILE_MAP's real stored name exactly, not this
    file's own underscored filename."""

    VERTICAL = "services-project"
    SYSTEM_PROMPT_ADDITIONS = ""
