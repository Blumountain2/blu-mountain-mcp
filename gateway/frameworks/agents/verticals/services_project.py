from ..base import BaseAgent


class ServicesProjectAgent(BaseAgent):
    """Services/Project vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered Services/Project framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised Services/Project framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "services-project"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: Services / Project

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Every HubSpot account ships with
a standard schema. Compute baseline metrics from validated standard
fields for every client. Custom properties, pipelines, and objects are
enrichments that improve fidelity, not requirements.

**Trust events, not statuses.** Status fields (lifecycle stage, lead
status) are editable by imports, forms, workflows, and manual edit.
Events (meeting completed, deal created, deal stage advanced, deal
closed-won, project completed) are recorded by the system from real
activities. The bot derives a contact’s stage from underlying events,
not from the lifecycle stage property.

**Record Source over Analytics Source.** `hs_object_source` and
`hs_object_source_label` are set automatically at record creation and
cannot be edited in most cases. `hs_analytics_source` became editable in
2024. The bot uses Record Source as primary attribution.

**Bookings are not revenue.** A signed SOW is a booking. Revenue
recognizes when work is delivered. A services business that conflates
these will mis-forecast badly. The bot tracks both and flags when
delivery infrastructure is absent.

**Repeat client revenue is the health metric.** Services businesses
don’t have NRR / GRR in the SaaS sense. The equivalent is the percentage
of revenue coming from existing clients (follow-on projects, retainer
continuation) versus new logos. This is the bot’s primary retention
signal.

**Validate before trusting.** Pre-flight reliability checks gate every
metric. When checks fail, metrics are reported with reduced confidence
and the data quality issue becomes the highest-priority finding.

**Personalize by Average Project Value and revenue mix.**
Recommendations adjust based on typical project size, retainer share of
revenue, and repeat-client concentration. A \$5K project shop and a
\$500K engagement firm need different RevOps infrastructure even if the
underlying issue looks identical.

------------------------------------------------------------------------

## 1. Category Definition

Project-based or retainer-based services businesses where revenue comes
from billable engagements. Includes consulting firms, agencies,
professional services arms, implementation partners, and
managed-services providers. Engagements have defined scope (SOW) and
finite or renewing duration. Revenue recognizes against delivered work,
not the signed contract date.

Distinct from SaaS because revenue is delivery-dependent, not
subscription-recurring. Distinct from Transactional because there is a
meaningful pre-sale discovery and scoping process. Hybrid models
(services firm with productized retainers) inherit from both this
framework and SaaS where retainers function like subscriptions.

## 2. Common GTM Motion

Inbound demand is heavily reputation-driven: referrals, content/thought
leadership, partner ecosystems, conference and community presence.
Outbound is possible but secondary; cold outbound rarely converts in
services because trust and proof are required.

The sales cycle is consultative. Discovery call to understand the
problem, scoping work to define the engagement, proposal/SOW
preparation, negotiation, signature. Cycle length varies widely: a small
project may close in a week, a large engagement in 6+ months.
Procurement and legal review extend timelines on enterprise deals.

Post-sale, delivery is the product. Project kickoff, milestones,
deliverables, invoicing tied to delivery. Renewal in services means
follow-on work: a next project, retainer continuation, or expansion of
scope. There is rarely a formal “renewal date” the way SaaS has.

## 3. KPIs by Function

### Marketing

Forms submitted by record source detail, qualified discovery calls
booked, attributed bookings, attributed delivered revenue,
content-to-pipeline contribution, brand search volume, referral volume,
partner-sourced pipeline.

### Sales

Bookings (signed SOW value), proposal-to-close conversion rate, average
project value, win rate, sales cycle, repeat client booking rate,
average days from first meeting to signed SOW, pipeline coverage, quota
attainment.

### Delivery (Customer Success equivalent)

Utilization rate, project margin, on-time milestone delivery, scope
creep rate (hours actual vs estimated), backlog (signed but not yet
delivered), days to project kickoff, project completion rate, retainer
renewal rate.

### Account / Servicing

Repeat client revenue rate, expansion revenue, NPS, time between
engagements, retainer attach rate, average client lifetime value
(cumulative project value across all engagements).

------------------------------------------------------------------------

## 4. HubSpot Schema Foundation

The bot computes baseline metrics from these standard fields. Property
names verified against HubSpot’s official documentation as standard.

### Contact (always present)

**Identity and ownership**: `createdate`, `hubspot_owner_id`,
`hubspot_owner_assigneddate`, `hs_marketable_status`, `hs_lead_status`,
`lifecyclestage` (treat as unreliable, see Section 5).

**Record Source (primary attribution, reliable)**: `hs_object_source`,
`hs_object_source_label`, `hs_object_source_detail_1`,
`hs_object_source_detail_2`, `hs_object_source_detail_3`. The Record
Source Detail values are particularly important in services because
referrals often show up as MANUAL or INTEGRATION (e.g. partner submitted
lead through a form), and pattern matching on the detail field reveals
the actual referral channel.

**Analytics Source (secondary, editable since 2024)**:
`hs_analytics_source`, `hs_analytics_source_data_1`,
`hs_analytics_source_data_2`, `hs_latest_source`,
`hs_latest_source_data_1`, `hs_latest_source_data_2`. Cross-check only.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`.

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open`, `hs_email_click`,
`hs_sales_email_last_opened`, `hs_sales_email_last_clicked`,
`hs_sales_email_last_replied`, `hs_email_sends_since_last_engagement`.

**Deal association**: `num_associated_deals`. For services, this number
is meaningful: clients with multiple deals are repeat clients.

### Company (always present)

`createdate`, `hubspot_owner_id`, `num_associated_contacts`,
`num_associated_deals`, `num_open_deals`, `recent_deal_amount`,
`recent_deal_close_date`, `total_revenue`, `days_to_close`,
`last_activity_date`, `notes_last_contacted`, `last_engagement_date`,
`lifecyclestage`, `industry`, `numberofemployees`, `annualrevenue`,
`hs_object_source`, `hs_object_source_label`.

`total_revenue` on Company is particularly useful for services because
it sums associated closed-won deal amounts, giving lifetime client value
with no custom configuration.

### Deal (always present)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype` (newbusiness, existingbusiness), `hubspot_owner_id`,
`hs_priority`, `num_associated_contacts`.

**SaaS revenue properties (rarely populated for services)**: `hs_arr`,
`hs_mrr`, `hs_acv`, `hs_tcv`. For project-based services, these are
usually empty because work is not recurring. For retainer-based
services, these may populate if line items are configured with recurring
billing. The bot does not treat these as primary signals for services.

**Close state**: `hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`, `hs_closed_won_date`, `closed_lost_reason`,
`closed_won_reason`, `days_to_close`.

**Stage history**: `hs_date_entered_<stageId>`,
`hs_date_exited_<stageId>`, `hs_time_in_<stageId>` for every stage.
`hs_v2_*` versions for default stages. `hs_date_entered_current_stage`
and `hs_time_in_current_stage` on Pro/Enterprise.

**Activity**: `notes_last_contacted`, `last_activity_date`,
`num_contacted_notes`, `num_notes`.

### Activity (Calls, Meetings, Emails, Tasks, Notes)

Same as standard schema: `hs_timestamp`, `hubspot_owner_id`,
`hs_activity_type`. Meetings: `hs_meeting_outcome`,
`hs_meeting_start_time`, `hs_meeting_end_time`. Calls:
`hs_call_disposition`, `hs_call_duration`, `hs_call_direction`,
`hs_call_status`.

### Custom Project object (services-specific, not standard)

Most mature services businesses build a custom Project object to track
delivery. This is not part of HubSpot’s standard schema. When present,
the bot looks for properties like project status (Active, On Hold,
Delivered, Cancelled), project start date, project end date, project
owner, hours estimated, hours actual, project type. When absent, the bot
falls back to using deal stage history to infer project lifecycle, which
is much less precise.

### What the bot derives from standard schema (no custom config required)

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source (primary) | `contact.hs_object_source` plus `hs_object_source_label` and detail fields |
| First conversion type | `contact.first_conversion_event_name` |
| MQL event (discovery call held) | meeting where `hs_meeting_outcome` is COMPLETED |
| SQL event (active scoping) | open deal in active sales pipeline |
| Opportunity event (SOW issued) | deal at “Proposal Sent” / “SOW Sent” stage |
| Customer event (SOW signed) | deal where `hs_is_closed_won` is true |
| Repeat customer | company with more than one closed-won deal where deal createdate of latest is more than 30 days after closedate of prior |
| Bookings | sum of `deal.amount` where closed-won in period |
| Pipeline value | sum of `deal.amount` where open and not closed |
| Sales cycle | `deal.days_to_close` |
| Stage velocity | `deal.hs_v2_time_in_<stageId>` (default) or `deal.hs_time_in_<stageId>` (custom) |
| Win rate | count of `hs_is_closed_won` divided by count of `hs_is_closed` over a cohort |
| Client lifetime value | `company.total_revenue` |
| Account inactivity | today minus `company.last_activity_date` |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: the client’s HubSpot is partially broken.
Services businesses have specific failure patterns that differ from
SaaS.

### Properties to treat as unreliable by default

**Lifecycle stage.** Same issue as SaaS. Editable, frequently misused.
The bot derives lifecycle from events.

**Analytics source.** Editable since 2024. Use Record Source instead.

**Deal amount.** Some services businesses enter total project value,
others enter monthly retainer value, others enter hourly rate times
estimated hours. The bot validates magnitude consistency and flags mixed
conventions.

`dealtype` rarely captured in services. The newbusiness /
existingbusiness distinction matters for repeat-client analysis but most
services HubSpots don’t use it. The bot infers new vs repeat by checking
whether the company has prior closed-won deals.

**Stage names.** Services pipelines vary wildly: some use “Discovery /
Scoping / Proposal / Negotiation / Closed Won,” others “Qualified / SOW
Drafted / SOW Sent / Signed.” The bot maps client stages to canonical
stages during onboarding analysis and flags pipelines that lack a clear
“proposal” or “SOW” stage.

**Project status (when custom object exists).** Often becomes stale
because no workflow keeps it current. The bot validates by checking
whether project status changes correlate with associated activity.

### Properties to trust by default

Record Source, object timestamps, boolean state flags (`hs_is_closed*`),
engagement recency, meeting outcomes. Same as the SaaS framework.

### Pre-flight reliability checks

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Lifecycle vs event consistency | % of contacts at Customer stage with no associated closed-won deal | \<2% | 2-10% | \>10% | Lifecycle-based metrics (low impact since framework uses event-based) |
| Repeat client visibility | distinct pipelines for new business and existing client work, OR `dealtype` populated on \>70% of closed-won | yes | partial | absent | Repeat client revenue rate, expansion analysis |
| Deal amount consistency | variance of `deal.amount` magnitude sanity check | manageable | suspect mixing | mixed conventions | Bookings, ACV, pipeline coverage |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source-level conversion (looser threshold for pre-Feb 2024 records) |
| Active ownership | % of records with `hubspot_owner_id` matching an active user | \>95% | 85-95% | \<85% | Owner-level reporting |
| Deal stage history validity | % of closed-won deals where stage history is monotonically forward | \>75% | 50-75% | \<50% | Stage conversion rates, sales cycle |
| Project tracking infrastructure | custom Project object OR delivery pipeline with status milestones | exists | partial (deal stage proxies project status) | absent | Backlog, delivery rate, project margin, on-time delivery |
| Closed-lost reason capture | % of closed-lost deals with `closed_lost_reason` populated | \>80% | 50-80% | \<50% | Loss analysis |
| Meeting outcome capture | % of past meetings with `hs_meeting_outcome` populated | \>70% | 40-70% | \<40% | MQL / discovery call tracking |
| Referral attribution clarity | distinct Record Source Detail values for referrals OR custom Referral Source property | yes | partial | absent | Channel mix analysis (referrals are typically the largest channel for services) |

### Confidence tiers for services metrics

**Tier 1 (high confidence, computable from validated standard
schema)**: - Contact volume by Record Source - Activity volume -
Discovery calls held (meetings with COMPLETED outcome) - Deal volume
created - Sales cycle - Stage velocity - Win rate (cohort) - Bookings
(sum of closed-won deal.amount) - Pipeline value (sum of open
deal.amount) - Client lifetime value (`company.total_revenue`) - Repeat
client identification (companies with multiple closed-won deals)

**Tier 2 (medium confidence, requires reliability check pass)**: -
Average project value (requires deal amount consistency) - Repeat client
revenue rate (requires repeat client visibility) - Pipeline coverage
(requires deal amount consistency) - Source-level conversion (requires
Record Source coverage)

**Tier 3 (requires custom infrastructure)**: - Backlog (signed but not
delivered) - requires project tracking infrastructure - Delivery rate (%
of bookings delivered in period) - requires project tracking -
Utilization rate - requires hours tracking integration (Harvest, Toggl,
ClickUp time, internal) - Project margin - requires hours tracking plus
rate / cost data - On-time milestone delivery - requires project
milestone tracking - Retainer renewal rate - requires retainer tracking
infrastructure

------------------------------------------------------------------------

## 6. Multi-Signal Event Detection

For each core services event, the bot uses primary, secondary, and
inferred signals.

### Lead (entry into the funnel)

**Primary signal**: contact created with `hs_object_source_label`
indicating an inbound entry (FORMS, INTEGRATION for known marketing
tools, MEETINGS, CHAT_FLOW) OR a tracked outbound first-touch activity.

**Secondary signal**: `first_conversion_event_name` populated,
particularly when the form name indicates intent (Contact Us, Discovery
Request, Project Inquiry).

**Cross-checks**: contacts created via IMPORT or MIGRATION usually
represent existing client contacts being added in bulk, not new leads.
Segregate from new lead cohort. For services specifically, look for
Record Source Detail values like “Referral” or partner-related strings
to identify referral leads, which are the most valuable channel.

### MQL (discovery call held)

**Primary signal**: at least one meeting engagement associated to the
contact where `hs_meeting_outcome` equals COMPLETED. The discovery call
is the meaningful first step in services because it confirms problem fit
and budget.

**Secondary signal**: `hs_meeting_start_time` is in the past AND
`hs_meeting_outcome` is not NO_SHOW, CANCELED, or RESCHEDULED.

**Cross-checks**: meetings without outcome capture default to “scheduled
past start” with reduced confidence. For services, distinguishing
discovery meetings from check-in or delivery meetings matters; when
meeting types are tracked, the bot uses `hs_activity_type` to filter to
sales-stage meetings only.

### SQL (scoping in progress)

**Primary signal**: contact is associated to at least one open deal in a
sales pipeline. The deal createdate is the SQL date.

**Secondary signal**: deal stage past initial intake (e.g. “Scoping,”
“Discovery Complete”) indicating active scoping work.

**Cross-checks**: a deal in “Scoping” or similar stage for more than 30
days without movement suggests stuck scoping, which is a common services
pattern. Flag for pipeline review.

### Opportunity (SOW issued)

**Primary signal**: deal at a stage representing proposal or SOW
issuance: “SOW Sent,” “Proposal Sent,” “Contract Sent,” or equivalent.
The bot maps the client’s pipeline to a canonical “proposal issued”
stage during onboarding analysis.

**Secondary signal**: associated quote object OR PandaDoc / DocuSign
activity logged.

**Cross-checks**: deal at the proposal stage for more than 30 days
without movement is a stuck proposal (common in services because
stakeholders go silent during budget cycles). Flag.

### Customer (SOW signed)

**Primary signal**: at least one deal associated to the company where
`hs_is_closed_won` equals true AND `hs_closed_won_date` is in the past.

**Secondary signal**: company-level `total_revenue` greater than zero
(auto-calculated from associated closed-won deals).

**Cross-checks**: closed-won with `hs_closed_won_date` in the future is
invalid. Multiple closed-won deals on the same company indicate repeat
client (good signal).

### Repeat client (follow-on engagement)

**Primary signal**: company has more than one closed-won deal where the
latest deal’s createdate is more than 30 days after the prior deal’s
closedate. The 30-day buffer prevents false positives from related deals
signed in the same negotiation cycle.

**Secondary signal**: `dealtype = existingbusiness` on the latest deal
(when `dealtype` discipline exists).

**Cross-checks**: this is the most valuable signal in services analytics
because repeat client revenue indicates retention health. The bot
calculates repeat client revenue as % of total bookings.

### Backlog (signed but not delivered)

**Best signal**: custom Project object with status = Active or In
Progress, where the associated deal is closed-won.

**Acceptable signal**: closed-won deal where the project end date
(custom property) is in the future.

**Inferred signal**: closed-won deal closed within the last X days,
where X is the typical project length for the client. This is rough and
confidence is reduced.

**Why this matters**: bookings minus delivered revenue equals backlog,
and backlog is a leading indicator of next-period revenue. Without
project tracking, backlog is invisible and forecasts are unreliable.

### Risk

**Primary signal**: stuck deal in pipeline (no stage advancement in 30+
days), client communication frequency dropping (`last_engagement_date`
more than 21 days for an active project), or project status property
indicating issue (On Hold, Blocked).

**Secondary signal**: scope creep flag (when hours tracking is synced
and actual hours exceed estimate by more than 25%).

**Tertiary signals**: NPS detractor response, reduced executive
engagement, key stakeholder departure (when tracked).

### Churn (engagement lapse)

**Best signal**: dedicated “lost client” lifecycle state OR custom
Churned property on company.

**Good signal**: client whose last closed-won deal is more than 18
months old AND no open deals AND no engagement in 90 days. (For
services, “churn” is fuzzier than SaaS because clients may simply not
have a current need without formally ending the relationship.)

**Inferred signal**: company in a customer state but
`last_activity_date` more than 12 months past. Flag as dormant rather
than churned because services clients re-engage opportunistically.

------------------------------------------------------------------------

## 7. Lifecycle Model

### Canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | Marketing-only audience | Form submission to low-intent asset, no meetings, no deals |
| Lead | Captured contact above subscriber intent | Form submission to higher-intent asset (Contact Us, Project Inquiry, Discovery Request) OR sales-logged first touch OR partner-submitted referral |
| MQL | Discovery call held | Meeting with `hs_meeting_outcome` = COMPLETED |
| SQL | Active scoping | Open deal associated to contact in sales pipeline |
| Opportunity | SOW issued | Deal at Proposal / SOW / Contract Sent stage |
| Customer | SOW signed | Closed-won deal associated to contact’s company |
| Repeat customer | Follow-on engagement | Second or later closed-won deal on the same company, with appropriate spacing |
| Evangelist | Multi-engagement advocate, referral source | Multiple closed-won deals OR referral attribution back to this contact |

### Mapping client-specific stages

Services pipelines vary widely. Common stage names mapped to canonical:

- “New Inquiry,” “Intake” map to Lead or SQL depending on whether a deal
  is created
- “Discovery,” “Qualifying” map to SQL
- “Scoping,” “Drafting Proposal” map to SQL or Opportunity depending on
  whether SOW exists
- “Proposal Sent,” “SOW Sent,” “Contract Sent” map to Opportunity
- “Negotiation,” “Procurement Review” remain Opportunity
- “Signed,” “Closed Won” map to Customer
- “Active,” “In Delivery,” “Implementation” map to Customer plus active
  project state (separate from lifecycle)
- “Delivered,” “Completed” map to Customer plus delivered project state

The post-customer states (Active, In Delivery, Delivered) should be
tracked through a project status property or Project custom object, not
by overloading lifecycle stage.

------------------------------------------------------------------------

## 8. Business Model

**Name**: Services / Project

**Inclusion rules**: - Revenue is engagement-based (project, retainer,
or hybrid) - Customer signs an SOW or services agreement - Sales cycle
requires consultative discovery and scoping - Delivery is the product;
recognized revenue depends on completed work - Team includes consultants
/ practitioners / strategists who are billable

**Exclusion rules**: - Pure subscription software → SaaS framework -
One-time non-engagement purchases (e.g. tool resale, one-off
transactions) → Transactional framework - Pure self-serve productized
services (e.g. fixed-price digital products with no consultative sale) →
Transactional or PLG depending on motion

**Hybrid handling**: services firms with productized retainers (monthly
recurring engagements with defined deliverables) inherit from SaaS for
the retainer portion. Apply both frameworks where relevant.

**Revenue trigger**: closed-won deal with services pipeline AND deal
stage past Closed Won, OR new row in Project custom object with status
changing to Active / In Progress.

------------------------------------------------------------------------

## 9. Funnel and Core Events

### Funnel stages

| Stage | Detection signal |
|:---|:---|
| Entry | Contact created with Record Source = FORMS, INTEGRATION (partner referral), MEETINGS, MANUAL (direct referral), or sales-logged first activity |
| Activation | Discovery call held (`hs_meeting_outcome` = COMPLETED) |
| Qualification | Open deal created |
| Scoping | Deal in early-stage scoping work |
| Proposal | Deal at SOW Sent / Proposal Sent stage |
| Conversion | Deal closed-won (signed SOW) |
| Delivery | Active project work |
| Repeat | Follow-on closed-won deal on existing client |
| Risk | Stuck deal, dropping engagement, scope creep, on-hold project |
| Churn (dormancy) | Customer with no recent deal or activity for 12+ months |

### Core events

Acquisition: new contact from a tracked source enters CRM. Activation:
discovery call held. Conversion: SOW signed (closed-won). Delivery:
project work executed. Repeat: follow-on engagement signed. Risk: stuck
deal or stalled project. Dormancy: client lapses without formal churn
event.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| Acquisition | Contact / Inquiry / Discovery form, Record Source = FORMS | – | New Contact with `hs_object_source` populated | Inbound call logged with sales user | Partner integration writing referral |
| Activation (MQL) | – | – | Meeting object created | Meeting with `hs_meeting_outcome` = COMPLETED | Calendly / Chili Piper integration write |
| Qualification (SQL) | – | Deal stage advances past intake | New deal in services pipeline | – | – |
| Proposal (Opportunity) | – | Deal stage = SOW Sent or equivalent | – | DocuSign / PandaDoc activity logged | Quote object created |
| Conversion (Customer) | – | `hs_is_closed_won` = true | New closed-won deal | – | Contract management system sync |
| Delivery | – | Project status = Active / In Progress | New Project custom object | Kickoff meeting logged | Project management tool sync (ClickUp, Asana, etc.) |
| Repeat | New project form on client portal | New closed-won deal on existing client company | – | Account expansion meeting | – |
| Risk | NPS detractor | Project status = On Hold / Blocked | – | No activity for 21+ days on active project | Hours-over-budget alert from time tracker |
| Dormancy | – | – | – | `last_activity_date` \> 12 months for customer | – |

------------------------------------------------------------------------

## 10. KPI Logic

### Acquisition and Funnel

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Acquisition volume | 1 | count of contacts created | `count(contact) where createdate in [period]` | rolling 30/90 day, quarter |
| Acquisition by Record Source | 1 | count grouped by source | group by `hs_object_source_label` | requires Record Source coverage check pass |
| Referral lead volume | 1 | count of contacts where Record Source Detail indicates referral OR custom Referral Source populated | filter on detail field strings or custom property | rolling |
| Discovery calls held | 1 | count of contacts with first held meeting in period | `count(distinct contact where exists meeting with hs_meeting_outcome = COMPLETED in [period])` | rolling |
| Lead-to-discovery rate | 1 | discovery’d / lead cohort | numerator: contacts whose first held meeting is within 60 days of contact createdate | 60 days from createdate |
| Discovery-to-deal rate | 1 | deal-created / discovery cohort | contacts with associated open deal whose deal createdate is within 30 days of first held meeting | 30 days from MQL |
| Deal-to-close rate | 1 | won / cohort | contacts whose first associated deal closes won | 365 days from SQL (services cycles often longer than SaaS) |

### Sales / Bookings

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Bookings | 1 | sum of closed-won deal value | `sum(deal.amount) where hs_is_closed_won and closedate in [period]` | rolling 30/90 day, quarter |
| Average project value | 2 | avg of closed-won deal amount | `avg(deal.amount) where hs_is_closed_won and closedate in [period]` | quarterly; requires deal amount consistency check pass |
| Win rate (cohort) | 1 | won / closed | `count(deal where hs_is_closed_won and createdate in [cohort]) / count(deal where hs_is_closed and createdate in [cohort])` | per quarter cohort, measured at 365 days |
| Sales cycle | 1 | avg days create to close | `avg(deal.days_to_close) where hs_is_closed_won and closedate in [period]` | 30/90/180 day rolling |
| Stage velocity | 1 | avg time in stage | `avg(deal.hs_v2_time_in_<stageId>) where hs_date_exited_<stageId> in [period]` (default) or non-v2 (custom) | 90 day rolling |
| Pipeline value | 1 | sum of open deal value | `sum(deal.amount) where hs_is_closed = false` | live |
| Pipeline coverage | 2 | open pipeline / quarterly bookings target | requires bookings target known | current quarter |
| Repeat client booking rate | 1 | bookings from companies with prior closed-won / total bookings | `sum(deal.amount where company has prior closed-won) / sum(deal.amount) where closed-won in [period]` | rolling |
| Repeat client count | 1 | distinct companies with more than one closed-won deal | `count(distinct company where count(closed-won deals) > 1)` | live |
| Client lifetime value | 1 | sum of closed-won across all engagements | `company.total_revenue` (auto-calculated) | per company |
| Average client value | 1 | avg of company.total_revenue across customer companies | `avg(company.total_revenue) where company has at least one closed-won deal` | per cohort or live |
| Closed-lost reason mix | 2 | count grouped by reason | requires closed-lost capture check pass | quarterly |
| Activities per rep | 1 | count by owner | `count(activity where hubspot_owner_id and hs_timestamp in [period])` | weekly |

### Delivery (Tier 3 unless noted)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| Backlog | 3 | sum of bookings not yet delivered | Project tracking infrastructure with delivery status |
| Delivery rate | 3 | delivered revenue / bookings | Project tracking with status transitions to Delivered |
| Utilization rate | 3 | billable hours / available hours per consultant | Hours tracking integration |
| Project margin | 3 | (revenue - hours cost) / revenue | Hours plus rate plus cost data |
| On-time milestone delivery | 3 | milestones met / milestones due | Project milestone tracking |
| Average project duration | 3 | avg of project end date - project start date | Project start/end tracking |
| Retainer renewal rate | 3 | retainers renewed / retainers due | Retainer pipeline or recurring deal tracking |
| Days to project kickoff | 3 | avg of kickoff date - signed SOW date | Kickoff event tracking |

When project tracking is absent, the bot reports each Tier 3 metric as a
structured gap with mapped recommendation. Building a Project custom
object with status workflow is typically the highest-impact
infrastructure recommendation for services clients.

------------------------------------------------------------------------

## 11. Project Value-Based Personalization

The services equivalent of ACV-based personalization. The bot adjusts
recommendations based on typical project size, retainer share of
revenue, and repeat-client concentration.

### What the bot looks up per client

**Median project value**: median of `deal.amount` across closed-won
deals in trailing 12 months. Validated against deal amount consistency
check.

**Project value distribution**: P25, P50, P75, P95. Indicates whether
engagements are tightly banded or vary widely.

**Retainer share of revenue**: when retainer pipeline OR recurring deal
type is identifiable, % of bookings coming from retainers vs project
work. High retainer share means more SaaS-like motion.

**Repeat client concentration**: % of revenue coming from companies with
more than one closed-won deal in trailing 24 months. High concentration
indicates relationship-driven model where client retention matters most.

**Average client lifetime value**: avg of `company.total_revenue` across
customer companies. Compares to average project value to indicate how
often clients return.

**Top-10 client concentration**: % of trailing 12-month bookings from
top 10 clients. High concentration is enterprise-tier services.

### Project value bands and how recommendations adjust

| Band | APV Range | Motion | Recommendation emphasis |
|:---|:---|:---|:---|
| Micro | \<\$10K | Productized, often self-serve adjacent | Volume automation, quick-turn delivery process, low-touch client experience. De-emphasize formal QBRs, deep account planning. |
| SMB | \$10K - \$50K | Inside sales, fast scoping | Pipeline volume, speed-to-discovery, sequence automation, light-touch project tracking, repeat-client nurture. |
| Mid-market | \$50K - \$250K | Full-cycle consultant + delivery lead | Structured pipeline, formal scoping process, project tracking infrastructure, named delivery leads, segmented onboarding. |
| Enterprise | \$250K - \$1M | Consultative team, multi-stakeholder | Account-based, multi-threading, security/procurement processes, executive sponsorship, formal program management, custom proposal infrastructure. |
| Strategic | \$1M+ | Account team, partner-level engagement | Bespoke. Strategic account planning, executive cadence, multi-year roadmap, custom contracting. |

### Hybrid: project plus retainer

When retainer share exceeds 30% of bookings, the bot treats the client
as hybrid and applies SaaS framework benchmarks for the retainer portion
(focused on retention, recurring revenue) plus services framework for
project work (focused on delivery, repeat-client rate).

### Repeat-driven vs new-logo-driven services

When repeat client concentration exceeds 60% of bookings, the bot
prioritizes account expansion and repeat-client motion recommendations
over new-logo acquisition. When repeat client concentration is below
30%, the bot prioritizes top-of-funnel and conversion recommendations
because the business is acquisition-dependent.

### Where this layer applies

- Diagnostic priority order
- Recommended template category weights (Micro businesses emphasize Lead
  Generation and Conversion; high-value businesses emphasize Account
  Servicing, Account Growth, Compensation)
- Benchmark band selection
- Tool recommendations (low-APV businesses get automation tools;
  high-APV businesses get account intelligence, proposal infrastructure,
  and project management depth)

------------------------------------------------------------------------

## 12. Benchmarks

Services benchmarks are less consolidated than SaaS because the category
is more fragmented. Sources include Service Performance Insight (SPI
Research), Gartner consulting, agency-specific surveys (Agency Edge,
Promethean Research), and Bessemer-style services-firm reporting.
Replace with Blu’s authoritative benchmarks when ingested. Caveats:
project type (consulting, agency, implementation, managed services) and
engagement model (project, retainer, hybrid) shift bands significantly.

### Bookings and Pipeline

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Pipeline coverage | 3-4x quarterly target | 2-3x | \<2x | Same standard as SaaS; services pipeline matures slower |
| Win rate (cohort) | 25-40% | 15-25% | \<15% | Higher than SaaS because services typically has more disqualification at top of funnel |
| Sales cycle Micro / SMB | \<30d | 30-60d | \>60d | Smaller projects close fast |
| Sales cycle Mid-market | 30-90d | 90-150d | \>150d |  |
| Sales cycle Enterprise | 90-180d | 180-270d | \>270d | Procurement extends timelines |
| Discovery-to-proposal rate | \>50% | 30-50% | \<30% | Of meetings held, % that lead to a proposal |
| Proposal-to-close rate | \>40% | 25-40% | \<25% | Of proposals sent, % that sign |
| Repeat client booking rate | \>50% | 30-50% | \<30% | The single most important services health metric. Below 30% means the business is purely acquisition-dependent. |

### Marketing and Top of Funnel

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Form-to-discovery rate | \>40% | 25-40% | \<25% | Higher than SaaS because services forms self-select intent |
| Discovery-held rate | \>75% | 60-75% | \<60% | Of scheduled discovery calls, % completed |
| Referral share of new bookings | \>30% | 15-30% | \<15% | Below 15% suggests reputation infrastructure is weak; referrals are the highest-converting channel |
| Content-to-pipeline contribution | varies widely; track trend | – | – | Use trend rather than absolute number |
| DQ rate (lead disqualification) | \<25% | 25-40% | \>40% | Slightly higher than SaaS tolerance because services is more fit-sensitive |

### Delivery (when tracked)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Utilization rate (billable consultants) | 70-85% | 60-70% | \<60% | Standard professional services benchmark |
| Project margin | \>40% | 25-40% | \<25% | Varies by service mix; strategic consulting higher, implementation lower |
| On-time milestone delivery | \>85% | 70-85% | \<70% |  |
| Scope creep rate (actual / estimated hours) | \<115% | 115-130% | \>130% | Some scope creep is normal; persistent overruns indicate scoping process problem |
| Average project duration vs estimated | within 10% | 10-25% over | \>25% over |  |

### Account Health

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Days from project end to next engagement (repeat clients) | \<90d | 90-180d | \>180d | Below 180 days, client is actively engaged; above suggests dormancy |
| Retainer renewal rate (when tracked) | \>85% | 70-85% | \<70% |  |
| NPS | \>40 | 20-40 | \<20 | Services NPS typically higher than SaaS due to relationship dynamics |
| % accounts with engagement in 90 days | \>70% | 50-70% | \<50% | Active client portfolio |

### Maturity stage adjustments

| Stage | Revenue range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Founder-led | \<\$1M | New logo acquisition, founder utilization, basic process | Looser benchmarks; project tracking informal; pipeline often ad hoc |
| Growth | \$1M - \$5M | Building delivery team, structured pipeline, repeat client motion | Standard benchmarks apply; first formal CRM and project tracking |
| Scale | \$5M - \$20M | Multiple practices, structured RevOps, comp design, utilization management | Tighter benchmarks; formal QBR cadence; retainer attach rate matters |
| Established | \$20M+ | Account-based growth, partner ecosystem, margin discipline, multi-practice management | Enterprise services benchmarks; rule-of-X analyses (e.g. Rule of 30 or 35 for services profitability + growth) |

The Revenue Stack Diagnostic order for services adapts: dormancy
(services churn) and repeat-client rate first when the client is at
Growth stage or beyond, pipeline volume first at founder-led stage.

------------------------------------------------------------------------

## 13. Required Data Minimum

**Identity**: email plus company domain.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts. For services specifically, referral attribution is critical;
if Record Source Detail values do not distinguish referrals, recommend a
custom Referral Source property.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate`, meeting `hs_timestamp`, deal stage history. Project start
and end dates if project tracking exists.

**Revenue value**: `deal.amount` populated on closed-won deals with
consistent magnitude convention (project value, not monthly value,
unless retainer).

**Activity / engagement signal**: at least one of
`notes_last_contacted`, `last_activity_date`, `last_engagement_date`
populated for active customers.

**Owner**: `hubspot_owner_id` populated on at least 80% of customer-tier
records, mapped to active users.

**Meeting outcomes**: `hs_meeting_outcome` populated on at least 50% of
past meetings.

**Repeat client distinction**: either `dealtype` populated on \>70% of
closed-won deals OR distinct pipelines for new business and existing
client work. Without this, repeat client revenue rate (the most
important services health metric) cannot be computed reliably.

When any floor is missed, the bot reports the gap as the
highest-priority finding before analyzing anything else.

------------------------------------------------------------------------

## 14. Rules and Edge Cases

### What happens when each event occurs

**Acquisition**: Record Source captured automatically, lifecycle
workflow may set Subscriber or Lead, owner assigned per routing rules.

**Activation (MQL)**: meeting marked COMPLETED, lifecycle workflow may
set MQL (cross-validated by bot), AE / consultant notified.

**Qualification (SQL)**: deal created in services pipeline, owner
assigned, scoping work begins.

**Opportunity (SOW)**: deal advances to Proposal / SOW Sent stage,
document sent via integration (PandaDoc, DocuSign), automated reminder
workflow if not signed within X days.

**Conversion (Customer)**: deal closes won, kickoff scheduled, project
record created (when custom object exists), delivery team assigned.

**Delivery**: project status transitions through Active / In Progress /
Delivered. Milestone tracking. Hours logged against project.

**Repeat**: new closed-won deal on existing company, attribution to
triggering signal (account expansion meeting, follow-on scoping,
retainer continuation).

**Risk**: alert to delivery lead or owner, project status updated,
recovery plan if needed.

**Dormancy**: customer with no activity 12+ months flagged on dormant
list, recirculated to BD or partner team for re-engagement (not treated
as formal churn unless client confirms).

### Duplicate handling

- Contacts: dedupe by email primary, secondary by company domain plus
  name.
- Companies: dedupe by domain primary, secondary by name plus location.
- Deals: dedupe by company plus pipeline plus open status. Multiple
  closed-won deals on a company are NOT duplicates in services; they are
  repeat engagements.

### Missing signals

- No Record Source captured: use `hs_analytics_source` as fallback with
  reduced confidence; treat as Unknown / Direct if both absent.
- No company associated: flag for enrichment.
- No deal value at close: flag for review, exclude from bookings rollup
  until corrected.
- No closed-lost reason: flag for capture process.
- No project tracking: flag as Tier 3 metric gaps with recommendation to
  build Project custom object or delivery pipeline.
- No retainer pipeline distinction: flag, recommend separating retainer
  deals from project deals.

### Out-of-order events

- Customer status before SQL events: services often has direct referral
  closes where the first deal closes within days of contact creation.
  Backfill MQL/SQL events at deal createdate.
- Repeat deal before original deal close: should not happen unless deals
  are misordered; flag.
- Project marked Delivered with deal still open: data integrity issue,
  flag.
- Project marked Active with deal closed-lost: data integrity issue,
  flag.

### Source conflicts

Same as SaaS framework. Record Source primary; Analytics Source
secondary; trust Record Source when they disagree. For services
specifically, partner referrals often arrive via INTEGRATION source with
the partner’s name in the detail field, while direct referrals arrive
via MANUAL or FORMS. Recommend a custom Referral Source property to
reduce ambiguity.

### Bad data handling

When pre-flight reliability checks fail at the alarm level, the bot
reports findings as follows:

1.  Lead with the data quality issue as the highest-priority
    recommendation.
2.  Compute Tier 1 metrics (event-based, schema-validated) and report
    with confidence.
3.  Compute Tier 2 metrics with reduced-confidence labels.
4.  Skip Tier 3 metrics that depend on the failing check, surface them
    as gaps with mapped recommendations.

Example output structure for a typical mid-stage services firm:

    Account: Example Consulting
    Pre-flight findings:
      Lifecycle vs event consistency: HEALTHY
      Repeat client visibility: ALARM (no dealtype discipline, no distinct pipelines for
        new vs existing client work)
      Project tracking infrastructure: ALARM (no Project custom object, no delivery pipeline)
      Record Source coverage: HEALTHY (91%)
      Deal amount consistency: HEALTHY

    Top recommendations:
      1. Build distinct New Business and Existing Client pipelines OR enforce dealtype on
         all deals. Without this, repeat client revenue rate (the primary services health
         metric) cannot be computed reliably.
      2. Build Project custom object with status workflow. Without delivery tracking,
         backlog and forecast are blind.

    Reliable metrics (Tier 1, event-based):
      Bookings: $1.2M last quarter
      Pipeline value: $3.8M open
      Pipeline coverage: 3.2x against $1.2M target (HEALTHY)
      Win rate: 34% on cohort closed in last quarter
      Sales cycle: 62 days average
      Discovery calls held: 47 last 90 days
      Discovery-to-deal rate: 68%

    Reduced-confidence metrics (Tier 2):
      Average project value: $73K (caveat: deal amount magnitude consistent, but cannot
        distinguish project from retainer values)
      Repeat client booking rate: estimated 41% based on company-level deal counts
        (caveat: no dealtype discipline; some "repeat" deals may be follow-up SOWs from
        same engagement)

    Gap-flagged metrics (Tier 3):
      Backlog: cannot compute. No project tracking infrastructure detected.
      Recommendation: Build Project custom object (Account Servicing template).
      Utilization rate: cannot compute. No hours tracking integration detected.
      Recommendation: Integrate Harvest, Toggl, or ClickUp time tracking.
      Project margin: cannot compute. Requires hours plus rate data.

    Project value personalization applied:
      Median project value: $73K (Mid-market band)
      P25-P75 range: $35K to $140K (mixed-segment, segmentation recommended)
      Repeat client concentration: estimated 41% (between thresholds, balanced acquisition
        and retention motion)
      Top-10 client concentration: 58% (relationship-driven, lean toward enterprise
        motion recommendations)
      Diagnostic priority: Repeat client rate fix first (data infrastructure), then
        backlog visibility, then top-of-funnel referral attribution.

------------------------------------------------------------------------

End of Services / Project framework.
"""
