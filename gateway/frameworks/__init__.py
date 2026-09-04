"""Public surface of the frameworks subsystem: storage and retrieval for
Blu Mountain's own-authored vertical frameworks, operational skill, and
runtime prompt (see openspec/changes/analysis-model-templates/). This
subpackage ingests and serves that content; it does not author it."""

from .guidance import FRAMEWORK_PROPERTY_GUIDANCE
from .ingest import FILE_MAP, ingest_directory
from .onboarding import (
    STATUS_CONFIRMED_IRRELEVANT,
    STATUS_CONFIRMED_RELEVANT,
    STATUS_NEEDS_REVIEW,
    OnboardingProfile,
    OnboardingProfileField,
    get_latest_profile_for_tenant,
    get_profile_for_tenant,
    produce_onboarding_profile,
    review_field,
)
from .profiling import FieldProfile, profile_tenant_fields
from .pull_agent import (
    MAX_TOOL_CALLS,
    ToolCallBudgetExceeded,
    run_client_agent,
)
from .store import (
    CONTENT_TYPE_CHALLENGE_LIBRARY,
    CONTENT_TYPE_FRAMEWORK,
    CONTENT_TYPE_OPERATING_PRINCIPLES,
    CONTENT_TYPE_PROMPT,
    CONTENT_TYPE_SKILL,
    CONTENT_TYPE_TEMPLATE_LIBRARY,
    AnalysisContent,
    get_latest,
    get_version,
    ingest,
    list_latest,
)
from .vertical import KNOWN_VERTICALS, get_tenant_vertical, set_tenant_vertical

__all__ = [
    "CONTENT_TYPE_FRAMEWORK",
    "CONTENT_TYPE_PROMPT",
    "CONTENT_TYPE_SKILL",
    "CONTENT_TYPE_CHALLENGE_LIBRARY",
    "CONTENT_TYPE_OPERATING_PRINCIPLES",
    "CONTENT_TYPE_TEMPLATE_LIBRARY",
    "AnalysisContent",
    "get_latest",
    "get_version",
    "ingest",
    "list_latest",
    "FILE_MAP",
    "ingest_directory",
    "FieldProfile",
    "profile_tenant_fields",
    "FRAMEWORK_PROPERTY_GUIDANCE",
    "STATUS_CONFIRMED_IRRELEVANT",
    "STATUS_CONFIRMED_RELEVANT",
    "STATUS_NEEDS_REVIEW",
    "OnboardingProfile",
    "OnboardingProfileField",
    "get_latest_profile_for_tenant",
    "get_profile_for_tenant",
    "produce_onboarding_profile",
    "review_field",
    "MAX_TOOL_CALLS",
    "ToolCallBudgetExceeded",
    "run_client_agent",
    "KNOWN_VERTICALS",
    "get_tenant_vertical",
    "set_tenant_vertical",
]
