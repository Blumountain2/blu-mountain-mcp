"""The set of verticals this project actually has a stored framework for.

Formerly also held a persisted, staff-set per-tenant vertical
(`set_tenant_vertical`/`get_tenant_vertical`, backed by `tenants.vertical`)
for the now-removed onboarding-profile pipeline. Removed 2026-09-08: a
client's vertical is fixed by which vertical class its agent subclasses
(`gateway/frameworks/agents/clients/*.py`), a git-tracked decision, not a
database value a caller resolves at call time — the same "codebase, not
Postgres rows" direction this project's agent architecture already took.
"""

from .ingest import FILE_MAP

# Every real vertical name this project actually stores a framework for —
# derived from FILE_MAP rather than duplicated by hand, so a new vertical
# added there is automatically valid here too.
KNOWN_VERTICALS = frozenset(
    name for content_type, name in FILE_MAP.values() if content_type == "vertical_framework"
)
