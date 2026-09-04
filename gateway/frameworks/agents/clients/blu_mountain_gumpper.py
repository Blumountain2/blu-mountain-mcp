"""Client agent for hub_id 148997330 ("Blu Mountain & Gumpper", the
baseline-tier HubSpot developer test portal). Migrated from the prior
client_agent_instances row (produced 2026-09-01), which had zero
confirmed-relevant fields — there was nothing real to carry over, only
the tenant identity and vertical assignment (openspec/changes/
client-vertical-agent-classes)."""

from ..registry import register_client_agent
from ..verticals.saas import SaaSAgent


@register_client_agent("148997330")
class BluMountainGumpperAgent(SaaSAgent):
    HUB_ID = "148997330"

    # Nothing confirmed yet — every one of these was still needs_review
    # in the prior tenant_onboarding_profile_fields rows (real state as
    # of 2026-09-03, not invented). Move a name here, into the real
    # object type's list, once a human actually decides it matters:
    #
    # CONTACT: email, firstname, lastname, hs_full_name_or_email, hs_object_id
    # COMPANY: domain, name, hs_object_id
    # CALL: hs_call_title, hs_object_id
    # EMAIL: hs_email_subject, hs_object_id
    # MEETING_EVENT: hs_meeting_start_time, hs_meeting_start_time_iso,
    #                hs_meeting_end_time, hs_meeting_end_time_iso,
    #                hs_meeting_title, hs_object_id
    # OBJECT_LIST: hs_list_name, hs_object_id
    # TASK: hs_task_subject, hs_object_id
    # USER: hs_email, hs_searchable_calculated_name, hs_object_id
    CONFIRMED_FIELDS: dict[str, list[str]] = {}
