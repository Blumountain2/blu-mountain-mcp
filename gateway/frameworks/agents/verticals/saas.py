from ..base import BaseAgent


class SaaSAgent(BaseAgent):
    """SaaS vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered SaaS framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised SaaS framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "saas"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: SaaS / Subscription

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Every HubSpot account ships with
a standard schema. Compute baseline metrics from validated standard
fields for every client. Custom properties, pipelines, and objects are
enrichments that improve fidelity, not requirements.

**Trust events, not statuses.** Status fields (lifecycle stage, lead
status) are editable by imports, forms, workflows, and manual edit. They
lie. Events (meeting completed, deal created, deal stage advanced, deal
closed-won) are recorded by the system from real activities and lie much
less often. The bot derives a contact’s stage from underlying events,
not from the lifecycle stage property.

**Record Source over Analytics Source.** HubSpot’s `hs_object_source`
and `hs_object_source_label` (Record Source) are set automatically at
record creation and cannot be manually edited in most cases. The older
`hs_analytics_source` (Original Source) became editable in 2024 and is
no longer reliable as a primary attribution signal. The bot uses Record
Source as primary; Analytics Source is treated as supplementary.

**Validate before trusting.** Even validated standard schema is reliable
only when the client has not broken it. Most have. Every metric runs
through pre-flight reliability checks before being reported with
confidence.

**Triangulate signals.** A “Customer” lifecycle stage means nothing
without a corresponding closed-won deal. A “Closed Won” deal means
nothing if the close date is in the future. The bot cross-validates
every event from at least two independent signals where possible.

**Confidence tiers.** Every KPI is labelled Tier 1 (computable from
validated schema, high confidence), Tier 2 (computable but
reliability-dependent, medium confidence), or Tier 3 (requires custom
infrastructure, flagged as gap if absent).

**Personalize by ACV.** Recommendations adjust based on the client’s
customer ACV distribution. A low-ACV high-volume business gets different
recommendations than a high-ACV white-glove business, even if the
underlying RevOps issue looks identical.

**Diagnostic priority shifts by maturity.** The default Revenue Stack
Diagnostic order (churn, pipeline, meetings, leads, expansion) applies
cleanly at Growth stage and beyond. At Early stage, invert: activation
and pipeline first, churn last because the data is too thin to trust.

------------------------------------------------------------------------

## 1. Category Definition

Sales-led or CS-led B2B SaaS where revenue comes from recurring software
subscriptions. Customers sign contracts (typically annual), are managed
by AEs through close and CSMs post-sale, and value is delivered
continuously over the contract term. This category specifically excludes
pure self-serve signup-to-paid flows (covered under PLG). A SaaS company
with a PLG side-motion inherits from both frameworks.

## 2. Common GTM Motion

Inbound demand from content, paid, organic search, and events feeds the
top of funnel. Outbound from BDR teams targets named ICP accounts. AEs
run discovery, demo, technical evaluation, security review, and
procurement. Sales cycles run 30 to 180 days depending on ACV. Contracts
close on a signed MSA or order form. Implementation hands off to CS or
services. Ongoing CSM relationship runs through renewal. Expansion comes
from seat additions, tier upgrades, module attach, and cross-sell.
Renewal is annual unless multi-year contract, processed through a
dedicated motion typically 60 to 90 days before renewal date.

## 3. KPIs by Function

### Marketing

Forms submitted (volume, by record source detail), meetings booked
(volume, by source), meeting-to-deal conversion rate, attributed
pipeline, attributed closed-won revenue, CAC by channel, demo requests,
cost per meeting booked, content-to-pipeline contribution, channel mix,
campaign attribution coverage.

### Sales

Deals created (volume, value), win rate (overall and by source/segment),
average sales cycle in days, average contract value, pipeline coverage
ratio, quota attainment, stage-to-stage conversion rates, new ARR
closed, average discount, deal velocity by stage, speed to lead,
activities per rep.

### Customer Success

Gross Revenue Retention, Net Revenue Retention, logo churn rate, revenue
churn rate, expansion ARR, time-to-value, customer health score
distribution, renewal rate (logo and revenue), product adoption by tier,
QBR completion rate, CSM book health.

### Support / Servicing

First response time, average resolution time, CSAT, NPS, ticket volume
by tier, reopens, escalation rate, deflection rate, ticket trend by
category, time-to-resolution by priority.

------------------------------------------------------------------------

## 4. HubSpot Schema Foundation

The bot computes baseline metrics from these standard fields, which
exist on every HubSpot account regardless of customization. Custom
properties are enrichments, not prerequisites. Every property listed
below has been verified against HubSpot’s official documentation as
standard.

### Contact (always present)

**Identity and ownership**: `createdate`, `hubspot_owner_id`,
`hubspot_owner_assigneddate`, `hs_marketable_status`, `hs_lead_status`,
`lifecyclestage` (treat as unreliable, see Section 5).

**Record Source (primary attribution, reliable)**: `hs_object_source`,
`hs_object_source_label`, `hs_object_source_detail_1`,
`hs_object_source_detail_2`, `hs_object_source_detail_3`. Set
automatically at creation, cannot be edited in most cases. This is the
bot’s primary attribution signal.

**Analytics Source (secondary, editable since 2024)**:
`hs_analytics_source`, `hs_analytics_source_data_1`,
`hs_analytics_source_data_2`, `hs_latest_source`,
`hs_latest_source_data_1`, `hs_latest_source_data_2`. Use as
supplementary context. Cross-check against Record Source.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`.

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open` (count of marketing emails
opened), `hs_email_click` (count of marketing emails clicked),
`hs_sales_email_last_opened`, `hs_sales_email_last_clicked`,
`hs_sales_email_last_replied`, `hs_email_sends_since_last_engagement`.

**Deal association**: `num_associated_deals`.

**Lifecycle date stamps (auxiliary, not primary)**:
`hs_lifecyclestage_lead_date`,
`hs_lifecyclestage_marketingqualifiedlead_date`,
`hs_lifecyclestage_salesqualifiedlead_date`,
`hs_lifecyclestage_opportunity_date`, `hs_lifecyclestage_customer_date`,
`hs_lifecyclestage_evangelist_date`. These auto-populate when lifecycle
stage advances, but lifecycle stage itself is editable, so these
timestamps reflect whoever last touched the lifecycle, not necessarily
real progression. Use only as cross-validation against event-based
detection.

### Company (always present)

`createdate`, `hubspot_owner_id`, `hubspot_owner_assigneddate`,
`num_associated_contacts`, `num_associated_deals`, `num_open_deals`,
`recent_deal_amount`, `recent_deal_close_date`, `total_revenue`,
`days_to_close`, `last_activity_date`, `notes_last_contacted`,
`last_engagement_date`, `lifecyclestage` (unreliable), `industry`,
`numberofemployees`, `annualrevenue`, `hs_object_source`,
`hs_object_source_label`.

### Deal (always present)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype` (newbusiness, existingbusiness), `hubspot_owner_id`,
`hs_priority`, `num_associated_contacts`.

**SaaS revenue properties (calculated from line items, require Sales Hub
Pro/Enterprise)**: `hs_arr`, `hs_mrr`, `hs_acv`, `hs_tcv`. These are
calculated from associated recurring line items based on billing
frequency and term length. They do NOT factor in `deal.amount`. If line
items are not used, these properties are empty regardless of
subscription tier.

**Close state**: `hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`, `hs_closed_won_date`, `closed_lost_reason`,
`closed_won_reason`, `days_to_close`.

**Stage history**: `hs_date_entered_<stageId>`,
`hs_date_exited_<stageId>`, `hs_time_in_<stageId>` for every stage in
every pipeline (auto-populated). Newer `hs_v2_date_entered_<stageId>`
and `hs_v2_time_in_<stageId>` exist for default stages only.
`hs_date_entered_current_stage` and `hs_time_in_current_stage` available
on Pro/Enterprise.

**Probability**: `hs_deal_stage_probability`, `hs_forecast_probability`.

**Activity**: `notes_last_contacted`, `last_activity_date`,
`num_contacted_notes`, `num_notes`.

### Activity (Calls, Meetings, Emails, Tasks, Notes)

**Common**: `hs_timestamp`, `hubspot_owner_id`, `hs_activity_type`.

**Meetings**: `hs_meeting_start_time`, `hs_meeting_end_time`,
`hs_meeting_outcome` (values include SCHEDULED, COMPLETED, NO_SHOW,
RESCHEDULED, CANCELED, plus any custom outcomes), `hs_meeting_title`,
`hs_meeting_location`, `outcome_completed_count`,
`outcome_no_show_count`, `outcome_canceled_count`,
`outcome_rescheduled_count`.

**Calls**: `hs_call_disposition`, `hs_call_duration` (milliseconds),
`hs_call_direction` (INBOUND, OUTBOUND), `hs_call_status`,
`hs_call_summary`, `hs_call_title`.

Activities associate to contacts, companies, and deals through the
standard association API.

### What the bot derives from standard schema (no custom config required)

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source (primary) | `contact.hs_object_source` plus `hs_object_source_label` and `hs_object_source_detail_1` |
| Acquisition source (secondary) | `contact.hs_analytics_source` (cross-check only) |
| First conversion type | `contact.first_conversion_event_name` |
| MQL event (meeting held) | meeting where `hs_meeting_outcome` is COMPLETED (or equivalent custom outcome) associated to the contact |
| SQL event (deal created in active pipeline) | open deal associated to the contact in a sales pipeline |
| Opportunity event (contract issued) | deal at “Contract Sent” stage or equivalent (mapped per client pipeline) |
| Customer event (deal won) | deal where `hs_is_closed_won` is true |
| Engagement recency | max of `notes_last_contacted`, `last_engagement_date`, `last_activity_date` |
| Sales cycle | `deal.days_to_close` |
| Stage velocity | `deal.hs_v2_time_in_<stageId>` (default stages) or `deal.hs_time_in_<stageId>` (custom) |
| Win rate | count of `hs_is_closed_won` divided by count of `hs_is_closed` over a cohort |
| Deal value | `deal.amount` always present, `deal.hs_arr` when line items configured and Pro/Enterprise tier |
| Owner workload | count of open deals where `hubspot_owner_id` equals X |
| Activity volume per rep | count of activities where `hubspot_owner_id` equals X within period |
| Account inactivity | today minus `company.last_activity_date` |
| Source-level conversion | cohort by `hs_object_source_label`, measure progression through events (meetings, deals, closed-won) |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: the client’s HubSpot is partially broken. Status
fields are editable, imports overwrite history, departed reps still own
records, custom processes have drifted. The bot validates before
reporting and downgrades confidence when checks fail.

### Properties to treat as unreliable by default

**Lifecycle stage** is the single most-broken field in HubSpot. It can
be set by imports, forms, workflows, manual edits, or integrations.
Common patterns include contacts bulk-set to Customer on import without
corresponding deals, lifecycle reversed when a contact unsubscribes and
gets re-imported, MQL/SQL stages skipped because reps move directly to
Opportunity, and Customer lifecycle never set when deals close-won
because of a missing workflow. The bot derives lifecycle from underlying
events (meeting held, deal created, deal closed-won) and uses the
lifecycle stage property only for cross-validation, never as the primary
signal.

**Analytics source / Original Source / Latest Source.** Became editable
in 2024. Bulk imports, contact merges, and certain workflows can
overwrite it. The bot uses Record Source (`hs_object_source`) as primary
and treats Analytics Source as supplementary.

**Deal amount** is used inconsistently. Some clients enter monthly
recurring value, others annual, others total contract value. Without
line items configured, `deal.hs_arr` is empty and the bot can’t infer
ARR from amount alone. The bot validates deal amount magnitude across
the customer base and flags when values look mixed.

**Owner ID.** Reps leave, their owner_id stays on hundreds of records,
deactivated users show up in reporting filters. The bot cross-checks
`hubspot_owner_id` against the active user list and filters or flags
accordingly.

**Deal stage.** Stage names change mid-year. Stages get added or
removed. Reps drag deals backwards. Stage history persists with old
stage IDs that no longer exist in the pipeline definition. The bot
validates stage progression against the current pipeline definition and
flags reversals or skipped stages.

### Properties to trust by default

**Record Source** (`hs_object_source`, `hs_object_source_label`,
`hs_object_source_detail_*`). Set at creation, cannot be edited in most
cases.

**Object timestamps** (`createdate`, `closedate`, `hs_closed_won_date`,
meeting `hs_timestamp`, deal stage `hs_date_entered_*`). These reflect
actual events. Edge case: imports can backdate them, but bulk-backdated
values are detectable.

**Boolean state flags** (`hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`). Computed from current `dealstage` value and
pipeline definition. Reliable for current state.

**Engagement recency** (`last_activity_date`, `last_engagement_date`,
`notes_last_contacted`). Computed from associated activities. Reliable,
with one caveat: `last_activity_date` includes future-scheduled
activities until they pass.

**Meeting outcomes** (`hs_meeting_outcome` on meeting engagements). Set
by users or integrations at the time of the meeting. More reliable than
lifecycle stage because it’s recorded against a specific time-bound
activity.

### Pre-flight reliability checks

The bot runs these before reporting any vertical-specific metric. Each
check returns a healthy / watch / alarm status that gates which metrics
carry confidence.

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Lifecycle vs event consistency | % of contacts at Customer stage with no associated closed-won deal | \<2% | 2-10% | \>10% | Any metric using lifecycle stage as primary signal (none if framework applied correctly) |
| Closed-won without lifecycle Customer | % of contacts associated with closed-won deals not at Customer lifecycle | \<5% | 5-15% | \>15% | Cross-validation diagnostic; indicates broken workflow |
| ARR coverage | % of customer companies with `hs_arr` \> 0 OR rolled-up custom ARR populated | \>80% | 50-80% | \<50% | NRR, GRR, ACV, expansion ARR |
| Line items used | % of closed-won deals with at least one associated line item | \>70% | 30-70% | \<30% | All `hs_arr/mrr/acv/tcv` calculations |
| New vs renewal distinction | % of closed-won deals with `dealtype` populated OR distinct renewal pipeline exists | \>70% | 40-70% | \<40% | New ARR vs retained split, renewal rate |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source-level conversion (note: lower for accounts pre-Feb 2024) |
| Active ownership | % of records with `hubspot_owner_id` matching an active user | \>95% | 85-95% | \<85% | All owner-level reporting, comp calculations |
| Deal stage history validity | % of closed-won deals where stage history is monotonically forward | \>75% | 50-75% | \<50% | Stage conversion rates, sales cycle, velocity |
| Renewal infrastructure | dedicated renewal pipeline OR subscription/contract object exists with renewal dates | exists | partial | absent | Renewal rate, renewal forecast, NRR/GRR |
| Closed-lost reason capture | % of closed-lost deals with `closed_lost_reason` populated | \>80% | 50-80% | \<50% | Loss analysis, churn vs competitive distinction |
| Meeting outcome capture | % of past meetings with `hs_meeting_outcome` populated to a non-default value | \>70% | 40-70% | \<40% | MQL detection (degrades to “meeting scheduled” instead of “meeting held”) |
| Deal amount consistency | variance of `deal.amount` magnitude across customer base sanity check | manageable | suspect mixing | inconsistent | All deal value rollups |

### Confidence tiers for SaaS metrics

Tier 1 metrics compute from validated standard schema and carry high
confidence regardless of customization.

- Contact volume by Record Source
- Activity volume by owner and type
- Meetings held (by `hs_meeting_outcome`)
- Deal stage velocity
- Sales cycle (closed-won)
- Account inactivity
- Email engagement metrics
- Win rate (because it’s deal-based, not lifecycle-based)

Tier 2 metrics compute but require pre-flight checks to clear before
reporting confidence.

- Lead-to-meeting conversion (requires Record Source coverage)
- Meeting-to-deal conversion (requires meeting outcome capture)
- Deal-to-customer conversion (Tier 1 if computed deal-side, Tier 2 if
  any lifecycle dependency)
- New ARR closed (requires new vs renewal distinction OR rough deal
  value sanity)
- ACV (requires line items used OR custom ARR property OR deal amount
  consistency)
- Pipeline coverage (requires deal amount consistency)
- Source-level conversion rates (requires Record Source coverage)

Tier 3 metrics require custom infrastructure that may or may not exist.
The bot reports them when the infrastructure is present and otherwise
surfaces the gap as a structured recommendation.

- NRR / GRR (requires renewal infrastructure plus point-in-time ARR
  snapshots)
- Renewal rate (requires renewal infrastructure)
- Churn rate (requires churn tracking infrastructure)
- Customer health score distribution (requires functioning health score
  property)
- Time to value (requires onboarding or value-milestone tracking)
- Expansion ARR (requires new vs renewal distinction)

------------------------------------------------------------------------

## 6. Multi-Signal Event Detection

For each core SaaS event, the bot uses primary, secondary, and inferred
signals. When signals agree, confidence is high. When they conflict, the
bot flags the inconsistency and uses the more reliable signal per the
priority below.

### Lead (entry into the funnel)

**Primary signal**: contact created with `hs_object_source_label`
indicating an inbound entry (FORMS, INTEGRATION for known marketing
tools, MEETINGS, CHAT_FLOW) OR a tracked outbound first-touch activity
(call logged, email sent by BDR).

**Secondary signal**: `first_conversion_event_name` populated (form
submission name).

**Cross-checks**: contact created via IMPORT or MIGRATION should not
count as a fresh lead unless source detail indicates the import was real
lead data; flag and segregate from inbound cohort for analysis.

### MQL (meeting held)

**Primary signal**: at least one meeting engagement associated to the
contact where `hs_meeting_outcome` equals COMPLETED (or the client’s
equivalent “held” custom outcome). The MQL date is the timestamp of the
first such meeting.

**Secondary signal**: `hs_meeting_start_time` is in the past AND
`hs_meeting_outcome` is not NO_SHOW, CANCELED, or RESCHEDULED. (Treats
“scheduled but not yet outcome-tagged” past meetings as probably held.)

**Cross-checks**: meetings with `hs_meeting_outcome` blank when start
time is more than 7 days in the past indicate a meeting outcome capture
problem; the bot flags this and falls back to “meeting scheduled past
start time” as an MQL proxy with reduced confidence. Lifecycle stage =
MQL without an associated held meeting is a lifecycle abuse signal, not
a real MQL.

### SQL (deal exists in active sales pipeline)

**Primary signal**: contact is associated to at least one open deal in a
sales pipeline. SQL date is the deal’s `createdate`.

**Secondary signal**: deal stage probability greater than zero AND deal
not in closed states.

**Cross-checks**: deal created without an associated contact suggests
manual deal entry, count it for SQL count but exclude from contact-level
conversion analysis. Lifecycle stage = SQL without an associated open
deal is not an SQL.

### Opportunity (contract issued)

**Primary signal**: deal at a “Contract Sent”, “Proposal”,
“Negotiation”, or equivalent late-stage value. The bot maps the client’s
pipeline to a canonical “contract issued” stage during onboarding
analysis (typically the second-to-last stage before Closed Won).

**Secondary signal**: deal with associated quote object OR
DocuSign/PandaDoc activity logged.

**Cross-checks**: deal at the contract stage for more than 60 days
without movement suggests a stuck deal, flag for pipeline hygiene; deal
jumping from early stage directly to Closed Won without passing through
Contract stage suggests stage bypass, flag for stage discipline review.

### Customer (closed-won)

**Primary signal**: at least one deal associated to the company where
`hs_is_closed_won` equals true AND `hs_closed_won_date` is in the past.

**Secondary signal**: company-level ARR property greater than zero (when
populated and reliable).

**Cross-checks**: closed-won deal with `hs_closed_won_date` in the
future is invalid, flag. Customer status without a closed-won deal
anywhere on the company is lifecycle abuse, do not count. Multiple
closed-won deals on the same company indicate either expansion (good) or
duplicate deals (bad); cross-check via `dealtype` and `closedate`
proximity.

### New business vs renewal vs expansion

This is the hardest distinction in SaaS HubSpot because most clients
lack renewal infrastructure.

**Best signal**: `dealtype` populated as newbusiness, existingbusiness
(with renewal/expansion sub-distinction) OR distinct pipelines for each.

**Good signal**: separate renewal pipeline AND separate expansion
pipeline.

**Acceptable signal**: closed-won deal where the associated company has
a prior closed-won deal more than 11 months old (likely renewal) OR
within 11 months (likely expansion).

**Inferred signal**: closed-won deal where company already has prior
closed-won deal, no `dealtype` distinction. The bot treats first close
as new business, subsequent closes within 11 months as expansion,
subsequent closes after 11+ months as renewal. Confidence flagged as
inferred.

### Risk

**Primary signal**: customer health score below threshold (when health
score reliability check passes).

**Secondary signal**: account inactivity, defined as today minus
`company.last_activity_date` greater than 60 days for an active
customer.

**Tertiary signals**: NPS detractor response in last 90 days, support
ticket spike (more than 3x baseline in 30 days), missed QBR (when QBR
meeting type is tracked), product usage drop (when usage data is
synced).

**Cross-checks**: a customer flagged as risk should appear in at least
two signals before being escalated. Single-signal risk flags go on a
watch list, not an action list.

### Churn

**Best signal**: deal closed-lost in dedicated churn pipeline.

**Good signal**: company-level “Churned” property is true with
`Churn Date` populated.

**Acceptable signal**: lifecycle stage moves from Customer to Other or
Lifecycle = Other with timestamp in period (only acceptable when
lifecycle integrity check passes).

**Inferred signal**: customer with no activity in the 90 days following
contractual renewal date (when renewal date is tracked).

**Cross-checks**: churn detected on lifecycle without corresponding deal
stage change is suspect (could be cleanup, not actual churn). Inferred
churn requires renewal date to be reliable.

------------------------------------------------------------------------

## 7. Lifecycle Model

The bot derives a contact’s stage from underlying events. The client’s
`lifecyclestage` property is used only for cross-validation, never as
the primary source of truth.

### Canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | Marketing-only audience | Form submission to a low-intent asset (newsletter, blog) AND no meetings, deals, or sales touches |
| Lead | Captured contact above subscriber intent | Form submission to a higher-intent asset (demo, contact, content gate) OR tracked inbound/outbound first touch by a sales user |
| MQL | Meeting held | At least one meeting with `hs_meeting_outcome` = COMPLETED (or equivalent) |
| SQL | Deal created in active sales pipeline | At least one open deal associated to the contact in a sales pipeline |
| Opportunity | Contract issued | Deal advanced to a “Contract Sent” or equivalent late stage |
| Customer | Deal closed-won | At least one closed-won deal associated to the contact’s company |
| Evangelist | Multi-product, advocate, NPS promoter | Multiple closed-won deals OR NPS promoter response within 12 months |

This is the bot’s internal model. The client’s actual `lifecyclestage`
property may differ. The bot reports both: derived stage (event-based,
reliable) and recorded stage (the lifecycle property, may be wrong).

### Mapping client-specific stages to canonical model

When the client uses non-standard lifecycle values (e.g. “Trial”,
“Onboarding”, “Active”, “Pilot”), the bot applies these mapping rules:

- “Trial”, “Pilot”, “POC” map to Opportunity if associated with an open
  deal in active sales motion
- “Onboarding”, “Implementing” remain a separate post-Customer state, do
  not collapse into Customer
- “Active”, “Engaged” map to Customer (post-onboarding)
- “PQL” (product qualified lead) maps to MQL with PLG flag
- “Churned”, “Lost” flag as terminal state
- Any custom stage that lacks a clear mapping is flagged for human
  review

### Why event-based detection is more reliable than lifecycle stage

Lifecycle stage in HubSpot is documented as “set through imports, forms,
workflows, or manually on a per contact basis.” That is, anyone or any
tool with edit access can change it, and the property does not maintain
a reliable history of legitimate transitions versus accidental
overwrites. Events (a meeting object created with a specific outcome, a
deal object at a specific stage, a closed-won deal record) are concrete
records of activity that cannot be retroactively faked without leaving
forensic evidence. The bot’s stage detection is therefore tied to the
underlying events, with lifecycle stage used only as a cross-validation
signal that fires reliability check warnings when it disagrees with the
event-derived stage.

------------------------------------------------------------------------

## 8. Business Model

**Name**: SaaS / Subscription (sales-led)

**Inclusion rules**: - Revenue is recurring (monthly or annual
contract) - Customer signs a contract or order form - Sales cycle
requires AE involvement (no fully self-serve signup-to-paid) - ACV
typically above \$5K per Blu’s diagnostic threshold for human-touch
viability - CSMs or account managers own renewal

**Exclusion rules**: - Pure self-serve signup-to-paid maps to PLG
framework - One-time non-recurring purchases map to Transactional
framework - Project-based delivery with finite end date maps to Services
/ Project framework

**Revenue trigger**: closed-won deal of recurring type
(`hs_is_closed_won` is true AND deal has recurring line items OR
`dealtype` indicates recurring), OR new row in subscription/contract
object, OR ARR property change on company from \$0 to greater than \$0.

------------------------------------------------------------------------

## 9. Funnel and Core Events

### Funnel stages

| Stage | Detection signal |
|:---|:---|
| Entry | Contact created via Record Source = FORMS, INTEGRATION, MEETINGS, CHAT, or sales-logged first activity |
| Activation | Meeting held (`hs_meeting_outcome` = COMPLETED) |
| Qualification | Open deal created in sales pipeline |
| Late stage | Deal at Contract / Proposal / Negotiation stage |
| Conversion | Deal closed-won |
| Expansion | Additional closed-won deal on existing customer (within 11 months of prior close) |
| Renewal | Closed-won deal on existing customer at renewal anniversary OR renewal pipeline close |
| Risk | Health score drop, support spike, low usage, NPS detractor, missed QBR, inactivity \> 60 days |
| Churn | Closed-lost in churn pipeline OR Churned property = true OR inferred via inactivity past renewal |

### Core events

Acquisition: new contact from a tracked source enters the CRM.
Activation: contact engages with sales (meeting held with outcome
COMPLETED). Conversion: deal closed-won (new ARR added). Expansion:
additional closed-won deal on existing customer. Renewal: contract
renewed at anniversary. Risk: indicator that customer may churn. Churn:
customer relationship ends, ARR removed.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| Acquisition | Form submission with Record Source = FORMS | – | New Contact with `hs_object_source` populated | Inbound call logged with sales user | Webhook from event tool, integration write |
| Activation (MQL) | – | – | Meeting object created | Meeting with `hs_meeting_outcome` = COMPLETED | Calendly/Chili Piper integration write |
| Qualification (SQL) | – | Deal stage advances past initial | New deal in sales pipeline | – | – |
| Late stage (Opportunity) | – | Deal stage = Contract Sent or equivalent | – | DocuSign/PandaDoc activity logged | Quote object created |
| Conversion (Customer) | – | `hs_is_closed_won` = true | New closed-won deal | – | Stripe/Chargebee/Maxio sync of new subscription |
| Expansion | Upsell form | – | New closed-won deal on existing customer | Meeting type = QBR or expansion | Product usage threshold crossed |
| Renewal | – | Renewal pipeline deal closes won | Deal in renewal pipeline | – | Subscription renewal in billing system |
| Risk | NPS form (detractor) | Health score drops below threshold | Support ticket in priority bucket | Inactivity beyond 60 days | Usage drop greater than threshold |
| Churn | Cancellation form | “Churned” property = true | Closed-lost deal in churn pipeline | – | Subscription cancelled in billing system |

------------------------------------------------------------------------

## 10. KPI Logic

Every metric below specifies the formula, the schema query, the lookback
window, and the confidence tier. The bot computes the metric and reports
it with the appropriate confidence label.

### Acquisition and Funnel

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Acquisition volume | 1 | count of contacts created | `count(contact) where createdate in [period]` | rolling 30/90 day, quarter |
| Acquisition by Record Source | 1 | count grouped by source | `count(contact) where createdate in [period]` group by `hs_object_source_label` | requires Record Source coverage check pass |
| Acquisition by Record Source Detail | 1 | count grouped by detail | same query, group by `hs_object_source_detail_1` | granularity into specific form, integration, etc. |
| MQL volume (meeting held) | 1 | count of contacts with first held meeting in period | `count(distinct contact_id where exists meeting with hs_meeting_outcome = COMPLETED and meeting.hs_timestamp in [period])` | rolling |
| Lead-to-MQL conversion | 1 | MQL’d contacts / cohort | numerator: contacts whose first held meeting falls within 90 days of contact createdate; denominator: contacts created in \[cohort period\] | 90 days from createdate |
| MQL-to-SQL conversion | 1 | SQL’d / MQL cohort | contacts with associated open deal whose deal createdate is within 60 days of first held meeting; denominator: MQL cohort | 60 days from MQL |
| SQL-to-Customer conversion | 1 | Customer / SQL cohort | contacts whose first associated deal closes won; denominator: SQL cohort | 365 days from SQL |
| Lead-to-Customer rate | 1 | Customers / cohort | full funnel cohort analysis | 365 days from createdate |
| Speed to lead | 1 | first activity time minus contact create time | `min(activity.hs_timestamp where activity.hubspot_owner_id is not null) - contact.createdate` | per cohort |
| Engagement recency | 1 | days since last engagement | `today - max(notes_last_contacted, last_engagement_date, last_activity_date)` | live |

### Sales

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Deals created | 1 | count of new deals | `count(deal) where createdate in [period]` | rolling 30/90 day, quarter |
| Win rate (cohort) | 1 | won / closed | `count(deal where hs_is_closed_won and createdate in [cohort]) / count(deal where hs_is_closed and createdate in [cohort])` | per quarter cohort, measured at 365 days |
| Sales cycle | 1 | avg days create to close | `avg(deal.days_to_close) where hs_is_closed_won and closedate in [period]` | 30/90/180 day rolling |
| Stage velocity | 1 | avg time in stage | `avg(deal.hs_v2_time_in_<stageId>) where hs_date_exited_<stageId> in [period]` (default stages); use non-v2 for custom | 90 day rolling |
| Stage conversion | 1 | deals exiting stage forward / deals entering stage | requires stage history validity check pass | per quarter |
| Pipeline coverage | 2 | open pipeline / quarterly quota | `sum(deal.amount) where hs_is_closed=false and closedate in [current Q]` divided by quota (when known) | current quarter |
| ACV | 2 | avg new ARR per won deal | `avg(deal.hs_arr) where hs_is_closed_won and dealtype='newbusiness' and closedate in [period]`. Fallback: `avg(deal.amount)` filtered to new business pipeline. | quarterly |
| New ARR closed | 2 | sum of new ARR | `sum(deal.hs_arr) where hs_is_closed_won and dealtype='newbusiness' and closedate in [period]` | rolling |
| Activities per rep | 1 | count by owner | `count(activity where hubspot_owner_id and hs_timestamp in [period])` | weekly |
| Closed-lost reason mix | 2 | count grouped by reason | requires closed-lost capture check pass | quarterly |
| Meetings held by source | 1 | count of held meetings grouped by contact source | meetings with `hs_meeting_outcome` = COMPLETED, joined to contact, grouped by `hs_object_source_label` | rolling |

### Customer Success and Retention (Tier 3 unless noted)

These metrics require renewal or churn infrastructure. The bot reports
them when infrastructure is present and otherwise surfaces the gap as a
structured recommendation.

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| GRR | 3 | (starting ARR minus churn minus contraction) / starting ARR | Period-start ARR snapshot infrastructure plus renewal infrastructure |
| NRR | 3 | (starting ARR minus churn minus contraction plus expansion) / starting ARR | Same as GRR plus expansion tracking |
| Logo churn rate | 3 | churned customers in period / starting customer count | Churn tracking infrastructure |
| Revenue churn rate | 3 | churned ARR in period / starting ARR | Churn tracking plus ARR coverage |
| Renewal rate (logo) | 3 | renewed deals / renewals due in period | Renewal pipeline OR subscription object with renewal dates |
| Renewal rate (revenue) | 3 | renewed ARR / ARR up for renewal | Renewal infrastructure plus ARR coverage |
| Expansion ARR | 3 | sum of expansion deals | Distinct expansion pipeline OR `dealtype` discipline |
| Time to value | 3 | days from close-won to first value milestone | Onboarding tracking with milestone events |
| QBR completion rate | 3 | QBRs held / QBRs due | Meeting type taxonomy with QBR identifier and `hs_meeting_outcome` capture |
| Health score distribution | 3 | count grouped by health score band | Functioning health score property with active update workflow |

### Diagnostic gap reporting

When a Tier 3 metric cannot be computed, the bot reports it as a
structured gap rather than absent data. Example:

    Metric: NRR
    Status: Cannot compute
    Gap: No renewal infrastructure detected (no renewal pipeline, no subscription object,
         no renewal date tracking)
    Recommendation: Build renewal pipeline with renewal date workflow OR custom Subscription object
    Template category: Account Servicing

This makes the gap actionable rather than just absent.

------------------------------------------------------------------------

## 11. ACV-Based Personalization Layer

The bot personalizes recommendations based on the client’s customer ACV
distribution. A recommendation that is high-priority for a low-ACV
high-volume business may be low-priority for a high-ACV white-glove
business, even when the underlying RevOps issue looks identical.

### What the bot looks up per client

**Median customer ACV**: median of `deal.hs_arr` across closed-won new
business deals in the trailing 12 months. Fallback: median of
`deal.amount` filtered to new business pipeline.

**ACV distribution**: P25, P50, P75, P95 of the same dataset. Indicates
whether the client has a tight ACV band or a wide range.

**Customer count**: count of distinct companies with at least one
closed-won deal. Indicates volume vs scarcity model.

**Customer tier (when populated)**: custom property on company (typical
names: Tier, Segment, ACV Band, Customer Tier). Used as override when
client has explicit tiering.

**Top customer ACV concentration**: % of total ARR coming from top 10
customers. High concentration indicates enterprise motion regardless of
median ACV.

### ACV bands and how recommendations adjust

| ACV Band | Range | Motion | Recommendation emphasis |
|:---|:---|:---|:---|
| Micro | \$0 - \$5K | Marketing-led, self-serve adjacent | High volume automation, nurture, lead recycling, light-touch onboarding, automated renewal. De-emphasize white-glove CS, manual QBRs, deep AE process. |
| SMB | \$5K - \$25K | Inside sales, BDR/AE | Pipeline volume, speed-to-lead, lead routing, sequence automation, tiered CS (digital for low end, human for top of band). |
| Mid-market | \$25K - \$100K | Full-cycle AE plus CSM | Balanced motion, structured pipeline, formal renewal process, named CSMs, segmented onboarding. Standard SaaS RevOps stack. |
| Enterprise | \$100K - \$500K | AE plus SE plus CSM, multi-stakeholder | Account-based, multi-threading, security/procurement processes, executive sponsorship, structured QBRs, custom integrations. Heavy weight on data quality, comp design, forecasting accuracy. |
| Strategic | \$500K+ | Account team, exec sponsor, custom motion | Bespoke. Recommendations focus on strategic account planning, executive cadence, mutual success plans, custom contract management. |

### Mixed-ACV clients

When the ACV distribution is wide (e.g. P25 = \$5K, P75 = \$80K), the
bot treats the client as multi-segment and recommends segmentation
infrastructure as a foundational priority. Without segmentation, any
single recommendation will be wrong for half the customer base.

### High-concentration clients

When top-10 ARR concentration exceeds 60%, the bot treats the client as
effectively enterprise regardless of median ACV, and weights
recommendations toward enterprise-tier infrastructure.

### Where this layer applies

The ACV personalization layer applies to:

- Diagnostic priority order (low-ACV businesses prioritize
  volume/efficiency; high-ACV businesses prioritize account depth and
  forecast accuracy)
- Recommended template category weights (low-ACV emphasizes Lead
  Generation and Lead Management; high-ACV emphasizes Account Growth,
  Account Servicing, Compensation)
- Benchmark band selection (Section 12 benchmarks are segmented; the bot
  picks the right column based on ACV)
- Tool recommendations (low-ACV businesses get automation-heavy tools;
  high-ACV businesses get coaching, intelligence, and account planning
  tools)

The personalization layer is applied after pre-flight reliability checks
pass. If reliability is broken, the bot fixes data quality first, then
applies personalization.

------------------------------------------------------------------------

## 12. Benchmarks

Starting ranges based on published industry sources (OpenView, KeyBanc,
Bessemer, SaaS Capital, ChartMogul). Replace with Blu’s authoritative
KPI benchmarks research guide when ingested. Segment caveats matter:
SMB, Mid-Market, and Enterprise SaaS look different on most metrics.
Early stage companies operate on different priorities than Scale stage.

### Retention

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| GRR (annual) | \>90% | 85-90% | \<85% | Enterprise targets \>95%; SMB tolerated lower |
| NRR (annual) | \>110% | 100-110% | \<100% | Top quartile SaaS exceeds 120%; below 100% means net contraction |
| Logo churn (annual) | \<10% | 10-15% | \>15% | SMB up to 20% acceptable; Enterprise \<5% expected |
| Revenue churn (annual) | \<8% | 8-12% | \>12% | Distinguish gross from net |
| 90-day onboarding churn | \<5% | 5-10% | \>10% | Per Blu’s existing template, leading indicator for downstream churn |

### Sales

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Win rate (Deal to Close) | 25-35% | 15-25% | \<15% | Cohort-based; period-based is noisier |
| Lead to Customer | 1-3% | 0.5-1% | \<0.5% | Inbound-heavy higher; outbound lower |
| Lead to MQL (meeting held) | 8-15% | 4-8% | \<4% | Depends on lead quality; inbound demos higher than gated content |
| MQL to SQL (deal created) | 50-65% | 35-50% | \<35% | High because meeting was already held |
| SQL to Customer | 25-35% | 15-25% | \<15% | Same as deal-level win rate |
| Sales cycle SMB (\<\$25K ACV) | \<60d | 60-90d | \>90d |  |
| Sales cycle Mid (\$25-100K) | 60-120d | 120-180d | \>180d |  |
| Sales cycle Enterprise (\>\$100K) | 120-180d | 180-270d | \>270d |  |
| Pipeline coverage | 3-4x | 2-3x | \<2x | Higher coverage required at early stage |
| Quota attainment (% of reps) | 60-70% | 45-60% | \<45% | Below 45% suggests quota or process problem |
| Speed to lead (inbound demo) | \<5 min | 5 min - 1 hr | \>1 hr | Per Blu’s template, 1 business day is the floor |
| Activities per rep per day | 30-50 | 15-30 | \<15 | BDR-heavy roles higher |

### Marketing and Funnel

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Form-to-meeting rate | \>25% | 15-25% | \<15% | Demo form requests; lower for content gated forms |
| Meeting-held rate | \>70% | 50-70% | \<50% | Of scheduled meetings, % that get to COMPLETED outcome |
| MQL volume MoM growth | \>5% | 0-5% | declining | Stage-dependent; declining at growth stage is alarm |
| Campaign attribution coverage | \>80% pipeline tied to campaign | 60-80% | \<60% |  |
| DQ rate (lead disqualification) | \<20% | 20-35% | \>35% | Per Blu’s diagnostic, above 35% means top of funnel quality issue |
| % database engaged in 30 days | \>25% | 15-25% | \<15% | Per Blu’s nurture template benchmarks |

### Customer Success

| Metric                        | Healthy | Watch   | Alarm | Notes                 |
|:------------------------------|:--------|:--------|:------|:----------------------|
| Time to value                 | \<60d   | 60-90d  | \>90d | Mid-market reference  |
| QBR completion rate (Tier 1)  | \>90%   | 70-90%  | \<70% |                       |
| CSAT                          | \>4.5/5 | 4.0-4.5 | \<4.0 |                       |
| NPS                           | \>40    | 20-40   | \<20  | SaaS median around 30 |
| % accounts engaged in 90 days | \>75%   | 50-75%  | \<50% |                       |

### Support

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|----|
| First response time (Tier 1) | \<1 hour | 1-4 hours | \>4 hours |  |
| First response time (Tier 2-3) | \<4 hours | 4-24 hours | \>24 hours |  |
| Average resolution time | \<24 hours | 24-72 hours | \>72 hours | Varies by complexity |
| Reopen rate | \<10% | 10-20% | \>20% | High reopens suggest first-touch resolution problem |

### Maturity stage adjustments

| Stage | ARR range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Early | \$0 - \$1M | Activation, pipeline volume | Looser benchmarks across the board; renewal infra not yet critical; churn data too thin to trust |
| Growth | \$1M - \$10M | Build foundational renewal/CS infrastructure; pipeline coverage matters | Standard benchmarks apply |
| Scale | \$10M - \$50M | Full RevOps stack, segmentation, NRR optimization, comp design | Tighter benchmarks; NRR and CAC payback become primary metrics |
| Mature | \$50M+ | Efficiency metrics (CAC payback, LTV/CAC, magic number), margin discipline | Enterprise-tier benchmarks; rule-of-40 evaluation standard |

The default Revenue Stack Diagnostic order (churn, pipeline, meetings,
leads, expansion) applies cleanly at Growth and beyond. At Early stage,
invert: pipeline and activation first, churn last because data is too
thin to trust.

### Segment caveats

| Segment | ACV range | Notable benchmark differences |
|:---|:---|:---|
| SMB | \<\$25K | Higher churn tolerance (up to 20% logo), shorter cycles, higher volume, lower CAC payback |
| Mid-Market | \$25K - \$100K | Standard benchmarks; balanced motion |
| Enterprise | \>\$100K | Tighter churn (\<5%), longer cycles, higher pipeline coverage required (4x+), procurement and security review extend timelines |

------------------------------------------------------------------------

## 13. Required Data Minimum

Below this floor, the bot cannot diagnose meaningfully and reports a
data adequacy gap before attempting analysis.

**Identity**: email plus company domain. Without these, dedupe and
attribution fail entirely.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts. Without this, channel diagnostics are guesswork. Note: HubSpot
accounts that existed before February 2024 may have lower coverage on
older records due to backfill limitations.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate`, meeting `hs_timestamp`, deal stage history
(`hs_date_entered_<stageId>`). Required for cohort analysis and
time-between-events.

**Revenue value**: at minimum `deal.amount` populated on closed-won
deals. Better is `deal.hs_arr` (requires line items). Without deal
value, no revenue diagnostics work.

**Activity / engagement signal**: at least one of
`notes_last_contacted`, `last_activity_date`, `last_engagement_date`
populated for active customers. Without engagement signal, account
health and risk diagnostics fail.

**Owner**: `hubspot_owner_id` populated on at least 80% of customer-tier
records, mapped to active users. Without ownership, no rep-level
diagnostics work.

**Meeting outcomes**: `hs_meeting_outcome` populated on at least 50% of
past meetings. Below this threshold, MQL detection degrades from
“meeting held” to “meeting scheduled past start time” with reduced
confidence.

When any of these floors are missed, the bot reports the gap as the
highest-priority finding before analyzing anything else.

------------------------------------------------------------------------

## 14. Rules and Edge Cases

### What happens when each event occurs

**Acquisition**: Record Source captured automatically by HubSpot,
lifecycle workflow may set Subscriber or Lead, owner assigned per
routing rules, sequence enrolment if applicable.

**Activation (MQL)**: meeting marked COMPLETED, lifecycle workflow may
set MQL (cross-validated by bot), AE notified.

**Qualification (SQL)**: deal created, lifecycle workflow may set SQL,
deal owner assigned.

**Late stage (Opportunity)**: deal advances to Contract stage, lifecycle
workflow may set Opportunity, contract sent via integration (DocuSign,
PandaDoc).

**Conversion (Customer)**: deal closes won, lifecycle workflow should
set Customer, CSM assigned, onboarding pipeline created, ARR populated,
renewal date set.

**Expansion**: new closed-won deal on existing customer, ARR updated,
attribution to triggering signal (QBR, usage threshold, champion
change).

**Risk**: alert to CSM or owner, health recalculated, save playbook
triggered if score below threshold.

**Churn**: lifecycle stage change to Other or Churned, churn reason
captured, recirculation to sales workspace if eligible for
re-engagement, health score archived.

### Duplicate handling

- Contacts: dedupe by email primary, secondary by company domain plus
  name.
- Companies: dedupe by domain primary, secondary by name plus location.
- Deals: dedupe by company plus pipeline plus open status. No duplicates
  allowed in active pipeline for the same opportunity.

The bot reports duplicate volume as a data hygiene metric and surfaces
high duplicate counts as a foundational fix before other diagnostics.

### Missing signals

- No Record Source captured (pre-Feb 2024 records): use
  `hs_analytics_source` as fallback with reduced confidence; treat as
  Unknown / Direct if both absent.
- No company associated: flag for enrichment, do not block lifecycle
  progression.
- No deal value at close: flag for review, exclude from ARR rollup until
  corrected.
- No closed-lost reason: flag for capture process improvement.
- No meeting outcome on past meeting: degrade MQL detection to
  “scheduled past start time” with reduced confidence.

### Out-of-order events

- Customer status before MQL or SQL events: indicates lifecycle stage
  abuse OR direct inbound close (some inbound demos go straight to
  closed-won within days). The bot checks deal createdate vs first
  associated meeting; if no meeting exists but deal closed-won, treat as
  direct close and backfill MQL/SQL events at deal createdate.
- Conversion before activation: allowed (direct closes); backfill
  activation timestamp from deal createdate.
- Expansion before onboarding completion: allowed, treat as strong PMF
  signal.
- Renewal before original close date: should not happen; flag as data
  integrity issue.
- Churn before customer status: should not happen; flag as data
  integrity issue.

### Source conflicts

- Record Source (`hs_object_source`) is set at creation and immutable in
  most cases. This is the primary attribution signal.
- Analytics Source (`hs_analytics_source`) is editable. If it conflicts
  with Record Source, trust Record Source.
- Latest Source updates with each new conversion event. Useful for
  re-engagement attribution but not for original attribution.
- When Record Source coverage is low (older accounts), fall back to
  Analytics Source and flag the metric as reduced confidence.

### Bad data handling

When pre-flight reliability checks fail at the alarm level, the bot
reports findings as follows:

1.  Lead with the data quality issue as the highest-priority
    recommendation.
2.  Compute Tier 1 metrics and report with confidence.
3.  Compute Tier 2 metrics, label them with reduced confidence and the
    specific reason.
4.  Skip Tier 3 metrics that depend on the failing check, surface them
    as gaps with mapped recommendations.

Example output structure when lifecycle vs event consistency check
fails:

    Account: Example Co
    Pre-flight findings:
      Lifecycle vs event consistency: ALARM (23% of Customer-stage contacts have no closed-won deal)
      Closed-won without lifecycle Customer: WATCH (8% of closed-won contacts not at Customer stage)
      ARR coverage: HEALTHY
      Record Source coverage: HEALTHY (94%)

    Top recommendation: Lifecycle stage cleanup required. 23% of contacts marked Customer
    have no closed-won deal, suggesting bulk import contamination. Bot reports use event-based
    detection (closed-won deal as Customer signal), so funnel metrics remain reliable; cleanup
    restores accurate lifecycle reporting in HubSpot UI for the team.

    Reliable metrics (Tier 1, event-based):
      Acquisition volume: 1,247 contacts last 90 days
      MQL volume (meetings held): 312 last 90 days
      SQL volume (deals created): 198 last 90 days
      Win rate: 31% on cohort closed in last quarter
      Sales cycle: 87 days average for closed-won
      Stage velocity: 14 days average in Discovery stage
      ...

    Reduced-confidence metrics (Tier 2):
      ACV: $42K (caveat: hs_arr populated on only 58% of closed-won deals; falling back to deal.amount which shows mixed magnitudes)
      ...

    Gap-flagged metrics (Tier 3):
      NRR: cannot compute. No renewal infrastructure detected.
      Recommendation: Build renewal pipeline (Account Servicing template).
      ...

    ACV personalization applied:
      Median customer ACV: $42K (Mid-market band)
      P25-P75 range: $18K to $78K (mixed-segment, segmentation recommended)
      Top-10 ARR concentration: 47% (not high-concentration enterprise)
      Diagnostic priority: standard SaaS Mid-market (pipeline, retention, expansion)

------------------------------------------------------------------------

End of SaaS / Subscription framework.
"""
