from ..base import BaseAgent


class SaaSAgent(BaseAgent):
    """SaaS vertical agent. Reads its raw framework text from
    analysis_content (content_type=framework, name="saas") — unchanged,
    still Blu Mountain's own authored content, never forked here.

    SYSTEM_PROMPT_ADDITIONS starts empty: the prior vertical_agent_templates
    row for "saas" was never actually filled in with real guidance before
    this change (confirmed against the live database), so there is
    nothing real to carry over — add real guidance here directly, as
    code, when there is some to add."""

    VERTICAL = "saas"
    SYSTEM_PROMPT_ADDITIONS = ""
