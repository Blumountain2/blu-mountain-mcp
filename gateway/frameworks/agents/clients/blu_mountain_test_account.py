"""Client agent for hub_id 149094230 ("Blu Mountain - Test Account", the
Enterprise/Marketing-Hub-Pro-equivalent HubSpot developer test portal,
with a real "Transaction" custom object). Migrated from the prior
client_agent_instances row (produced 2026-09-01), which had zero
confirmed-relevant fields and — incorrectly — pointed at the saas
template; the tenant's real vertical is marketplace, corrected directly
in the database as part of this change (openspec/changes/
client-vertical-agent-classes)."""

from ..registry import register_client_agent
from ..verticals.marketplace import MarketplaceAgent


@register_client_agent("149094230")
class BluMountainTestAccountAgent(MarketplaceAgent):
    HUB_ID = "149094230"

    # Nothing confirmed yet — every one of these was still needs_review
    # in the prior tenant_onboarding_profile_fields rows (real state as
    # of 2026-09-03, not invented). Move a name here, into the real
    # object type's list, once a human actually decides it matters.
    # This tenant's real custom "Transaction" object (objectTypeId
    # 2-252820399, confirmed live via list_custom_objects) has no
    # confirmed fields yet either — add an entry keyed by that
    # objectTypeId once one is decided on.
    #
    # CONTACT: email, firstname, lastname, hs_full_name_or_email, hs_object_id
    # COMPANY: domain, name, hs_object_id
    # DEAL: amount, closedate, closedate_iso, dealname, dealstage, hs_object_id
    # CAMPAIGN: hs_name, hs_object_id
    # CALL: hs_call_title, hs_object_id
    # EMAIL: hs_email_subject, hs_object_id
    # MEETING_EVENT: hs_meeting_start_time, hs_meeting_start_time_iso,
    #                hs_meeting_end_time, hs_meeting_end_time_iso,
    #                hs_meeting_title, hs_object_id
    # OBJECT_LIST: hs_list_name, hs_object_id
    # TASK: hs_task_subject, hs_object_id
    # USER: hs_email, hs_searchable_calculated_name, hs_object_id
    CONFIRMED_FIELDS: dict[str, list[str]] = {}
