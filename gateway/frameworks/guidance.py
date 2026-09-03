"""Per-vertical "trust by default" / "unreliable by default" property
guidance, extracted from each vertical framework's own "Data Quality
Reality Check" section (context/Blu Mountain Documentation/Artifacts/
*_Vertical_Framework*.md — gitignored real client content, now stored via
frameworks.store).

Deliberately hand-curated, not auto-parsed from the framework prose at
runtime: these documents are long-form text, not structured data, and a
mechanical parser risks silently misreading exactly the kind of nuance
that matters here (getting this wrong would mean judging a real client's
real data as trustworthy or not on a bad assumption). Only properties the
framework text actually names are listed — a short list for a vertical
means the framework didn't name more specifics beyond general statements,
not that extraction failed.

Provenance: extracted by an agent read against the real source text, then
spot-checked by hand against two entries before being trusted — both spot
checks found a real transcription issue, both fixed here:
- `hs_date_entered_*` (SaaS/Services frameworks' own text: "deal stage
  `hs_date_entered_*`") is a property-name *pattern*, not one property —
  the real per-stage properties it refers to (e.g.
  `hs_date_entered_qualifiedtobuy`) have no fixed name this profiling
  logic's exact-match comparison could check against, so it's omitted
  rather than included as a non-matching literal.
- `company.total_revenue` (Transactional framework's own text) is
  disambiguating which *object* the property lives on for a reader
  coming from a Deal's perspective — normalized here to `total_revenue`,
  since this profiling logic already matches within one object type's
  own record at a time.
The remaining entries were not independently re-verified line-by-line
against the source text beyond this — revisit if a real onboarding run
ever flags one as wrong.
"""

FRAMEWORK_PROPERTY_GUIDANCE: dict[str, dict[str, list[str]]] = {
    "saas": {
        "trust_by_default": [
            "hs_object_source",
            "hs_object_source_label",
            "hs_object_source_detail",
            "createdate",
            "closedate",
            "hs_closed_won_date",
            "hs_timestamp",
            "hs_is_closed",
            "hs_is_closed_won",
            "hs_is_closed_lost",
            "last_activity_date",
            "last_engagement_date",
            "notes_last_contacted",
            "hs_meeting_outcome",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
            "hubspot_owner_id",
            "dealstage",
        ],
    },
    "plg": {
        "trust_by_default": [
            "hs_object_source",
            "createdate",
            "hs_is_closed",
            "hs_is_closed_won",
            "hs_is_closed_lost",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
        ],
    },
    "marketplace": {
        "trust_by_default": [
            "hs_object_source",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
            "dealtype",
        ],
    },
    "ecommerce": {
        "trust_by_default": [
            "hs_object_source",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
        ],
    },
    "services-project": {
        # This vertical's own framework text says "Same as the SaaS
        # framework" for trust_by_default rather than re-enumerating —
        # copied from saas's list above, not independently derived.
        "trust_by_default": [
            "hs_object_source",
            "hs_object_source_label",
            "hs_object_source_detail",
            "createdate",
            "closedate",
            "hs_closed_won_date",
            "hs_timestamp",
            "hs_is_closed",
            "hs_is_closed_won",
            "hs_is_closed_lost",
            "last_activity_date",
            "last_engagement_date",
            "notes_last_contacted",
            "hs_meeting_outcome",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
            "dealtype",
            "dealstage",
        ],
    },
    "transactional": {
        "trust_by_default": [
            "hs_object_source",
            "total_revenue",
        ],
        "unreliable_by_default": [
            "lifecyclestage",
            "hs_analytics_source",
            "amount",
            "dealtype",
            "dealstage",
        ],
    },
}
