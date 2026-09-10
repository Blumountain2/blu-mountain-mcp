from ..base import BaseAgent


class TransactionalAgent(BaseAgent):
    """Transactional vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered Transactional framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised Transactional framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "transactional"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: Transactional

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Every HubSpot account ships with
a standard schema. Compute baseline metrics from validated standard
fields for every client. Custom properties, pipelines, and objects are
enrichments that improve fidelity, not requirements.

**Trust events, not statuses.** Status fields (lifecycle stage, lead
status) are editable by imports, forms, workflows, and manual edit.
Events (configurator submission, quote sent, deal closed-won, order
delivered) are recorded by the system from real activities. The bot
derives a contact’s stage from underlying events, not from the lifecycle
stage property.

**Record Source over Analytics Source.** `hs_object_source` and
`hs_object_source_label` are set automatically at record creation and
cannot be edited in most cases. `hs_analytics_source` became editable in
2024. The bot uses Record Source as primary attribution.

**Customer is at the company, not the deal.** A customer is a company
that has bought at least once. Each deal is a transaction. This
distinction matters because transactional businesses often confuse “deal
closed” with “customer acquired” and double-count customers when the
same company buys multiple times.

**Detect retention pattern, do not assume it.** Some transactional
categories are one-and-done by nature (carports, custom builds, capital
equipment, real estate, wedding services). Some are occasional-repeat
(commercial HVAC, residential remodelling, business equipment). Some are
regular-repeat (industrial supplies, recurring B2B equipment refresh,
automotive parts). The bot must observe the actual repeat-purchase
pattern in the client’s data and apply retention logic conditionally.
Recommending repeat-purchase nurture for a one-and-done business is
wrong; recommending acquisition focus for a high-repeat business is also
wrong.

**Validate before trusting.** Pre-flight reliability checks gate every
metric.

**Personalize by Average Order Value, retention pattern, and cycle
length.** All three drive recommendation priority and the appropriate
retention proxy.

------------------------------------------------------------------------

## 1. Category Definition

Transactional businesses sell goods or services through one-time
purchases with a meaningful pre-sale process. Includes industrial
equipment, capital goods, custom-manufactured products, vehicles,
residential and commercial construction, real estate, one-time
professional services, and considered B2C purchases. Customers may buy
once and never return, may buy occasionally, or may buy regularly
without any contractual recurrence.

Distinct from SaaS because there is no subscription. Distinct from
E-commerce because the sales process typically involves quoting,
configuration, or stakeholder coordination rather than
catalog-and-checkout. Distinct from Services because the deliverable is
typically a tangible product or a defined non-consultative service
rather than ongoing engagement.

Hybrid cases are common: a transactional business with a service
contract attached (e.g. sell equipment plus annual maintenance) inherits
from this framework for the equipment side and from SaaS or Services for
the recurring side.

## 2. Common GTM Motion

Marketing carries heavy weight: paid search, SEO, paid social, content,
local search and reviews (for location-driven categories), trade shows,
partner channels. Lead capture happens through forms (Contact, Quote
Request, Configurator), phone calls, walk-ins, and partner referrals.

The sales cycle ranges widely. Low-consideration purchases close in
days. High-consideration purchases (capital equipment, real estate,
custom builds) take months and involve site visits, technical
evaluation, financing, and multi-stakeholder approval.

Quoting is common. Many transactional businesses use a
quote-and-negotiate model rather than fixed pricing. Quote-to-close
conversion is a primary metric.

Post-sale, the relationship may include delivery coordination,
installation, warranty service, and re-engagement for future purchases.
Whether re-engagement is meaningful depends on the category, which the
bot detects rather than assumes.

## 3. KPIs by Function

### Marketing

Leads created by Record Source Detail, cost per lead, MQL volume,
attributed pipeline, attributed revenue, ROAS by channel, brand search
volume, review volume and rating, referral attribution.

### Sales

Quotes sent, quote-to-close conversion rate, average order value, win
rate, sales cycle, pipeline coverage, quota attainment, average days
from first contact to close.

### Customer relationship indicators (presented neutrally; weighting depends on detected retention pattern)

Repeat purchase rate, average time between purchases, customer lifetime
value, dormancy rate, referral rate, NPS, review submission rate,
win-back rate.

### Service / Post-Sale

Warranty claim rate, post-sale issue rate, time-to-installation,
time-to-delivery, customer satisfaction at delivery, complaint
resolution time.

The Customer relationship indicators are not all equally important. The
bot determines which apply primarily based on the detected retention
pattern (Section 6). For a one-and-done category, review and referral
metrics are primary; repeat purchase rate is informational. For a
regular-repeat category, repeat purchase rate and time between purchases
are primary; review and referral remain useful but secondary.

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
`hs_object_source_detail_2`, `hs_object_source_detail_3`. Critical for
transactional because attribution drives marketing efficiency analysis.
Pattern matching on detail values reveals specific campaigns, ad groups,
configurator entries.

**Analytics Source (secondary, editable since 2024)**:
`hs_analytics_source`, `hs_analytics_source_data_1`,
`hs_analytics_source_data_2`, `hs_latest_source`,
`hs_latest_source_data_1`, `hs_latest_source_data_2`. Cross-check only.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`. The first conversion is highly
predictive of purchase intent in transactional (e.g. a configurator
submission converts much higher than a content download).

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open`, `hs_email_click`,
`hs_sales_email_last_opened`, `hs_sales_email_last_clicked`,
`hs_sales_email_last_replied`, `hs_email_sends_since_last_engagement`.

**Deal association**: `num_associated_deals`.

### Company (always present)

`createdate`, `hubspot_owner_id`, `num_associated_contacts`,
`num_associated_deals`, `num_open_deals`, `recent_deal_amount`,
`recent_deal_close_date`, `total_revenue`, `days_to_close`,
`last_activity_date`, `notes_last_contacted`, `last_engagement_date`,
`lifecyclestage`, `industry`, `numberofemployees`, `annualrevenue`,
`hs_object_source`, `hs_object_source_label`.

`total_revenue` on Company auto-sums associated closed-won deal amounts,
giving lifetime customer value with no custom configuration.
`recent_deal_close_date` lets the bot compute days-since-last-purchase
for every customer without setup.

### Deal (always present)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype` (newbusiness, existingbusiness), `hubspot_owner_id`,
`hs_priority`, `num_associated_contacts`.

**SaaS revenue properties (rarely populated for transactional)**:
`hs_arr`, `hs_mrr`, `hs_acv`, `hs_tcv`. Generally empty for
transactional. Ignore unless service contract attached.

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

Standard schema. `hs_timestamp`, `hubspot_owner_id`, `hs_activity_type`.
Meetings: `hs_meeting_outcome`, `hs_meeting_start_time`. Calls:
`hs_call_disposition`, `hs_call_duration`, `hs_call_direction`. Inbound
calls are a major lead channel for many transactional categories.

### What the bot derives from standard schema (no custom config required)

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source | `contact.hs_object_source` plus `hs_object_source_label` and detail fields |
| First conversion type | `contact.first_conversion_event_name` |
| Quote / proposal sent | deal at “Quote Sent” / “Proposal” stage |
| Order placed | deal where `hs_is_closed_won` is true |
| First-time customer | contact’s company has exactly one closed-won deal |
| Repeat customer | company has more than one closed-won deal |
| Time between purchases | difference between consecutive `deal.closedate` values on the same company |
| Customer lifetime value | `company.total_revenue` |
| Last purchase date | `company.recent_deal_close_date` |
| Days since last purchase | today minus `company.recent_deal_close_date` |
| Sales cycle | `deal.days_to_close` |
| Win rate | count of `hs_is_closed_won` divided by count of `hs_is_closed` over a cohort |
| Pipeline value | sum of `deal.amount` where open and not closed |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: the client’s HubSpot is partially broken.

### Properties to treat as unreliable by default

**Lifecycle stage.** Editable, frequently misused. The bot derives
lifecycle from events.

**Analytics source.** Editable since 2024. Use Record Source instead.

**Deal amount.** Transactional businesses often enter deal value
inconsistently: some include tax, others don’t; some include shipping or
installation, others split these into separate line items. The bot
validates magnitude and flags mixed conventions.

`dealtype` rarely captured in transactional. The bot infers repeat
status from company-level deal counts when `dealtype` is absent.

**Customer status at the contact level.** Transactional businesses often
have multiple contacts per company. The bot operates at the company
level for customer status.

**Stage names.** Map to canonical stages during onboarding analysis.

### Properties to trust by default

Record Source, object timestamps, boolean state flags, engagement
recency, `company.total_revenue` (auto-calculated).

### Pre-flight reliability checks

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Customer status at company level | % of companies with at least one closed-won deal that have lifecycle = Customer | \>85% | 60-85% | \<60% | Customer count, repeat purchase rate, lifetime value |
| Deal amount consistency | variance of `deal.amount` magnitude sanity check | manageable | suspect mixing | mixed conventions | AOV, bookings, pipeline value |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source-level conversion, ROAS by channel |
| Active ownership | % of records with `hubspot_owner_id` matching an active user | \>95% | 85-95% | \<85% | Owner-level reporting, comp |
| Deal stage history validity | % of closed-won deals where stage history is monotonically forward | \>75% | 50-75% | \<50% | Stage conversion rates, sales cycle |
| Quote-stage capture | distinct “Quote Sent” or equivalent stage exists, with population | exists, populated | exists, sparse | absent | Quote-to-close rate, proposal-stage analysis |
| Closed-lost reason capture | % of closed-lost deals with `closed_lost_reason` populated | \>80% | 50-80% | \<50% | Loss analysis, competitive insights |
| Repeat customer visibility | `dealtype` populated on \>70% of closed-won OR distinct pipelines for new vs existing customer work | yes | partial | absent | Repeat purchase rate clarity (note: only matters when retention pattern detection identifies the business as repeat-capable) |
| Sufficient deal history for pattern detection | customer companies with closed-won deals tracked for \>24 months OR \>100 closed-won deals total | yes | partial | absent | Retention pattern detection (when absent, fall back to category metadata or owner input) |

### Confidence tiers for transactional metrics

**Tier 1 (high confidence, computable from validated standard
schema)**: - Contact volume by Record Source - Activity volume - Quote /
proposal volume - Deal volume created - Bookings (sum of closed-won deal
amount) - Pipeline value - Sales cycle - Stage velocity - Win rate
(cohort) - First-time customer count - Repeat customer count - Customer
lifetime value (`company.total_revenue`) - Days since last purchase per
customer - Time between purchases distribution

**Tier 2 (medium confidence, requires reliability check pass)**: -
Average order value (requires deal amount consistency) - Quote-to-close
conversion (requires quote-stage capture) - Repeat purchase rate
(requires customer status at company level) - Source-level conversion
rates (requires Record Source coverage) - Pipeline coverage (requires
deal amount consistency)

**Tier 3 (requires custom infrastructure)**: - Warranty claim rate
(requires service ticket tracking with order linkage) - Time-to-delivery
(requires delivery date tracking) - Time-to-installation (requires
installation date tracking) - NPS, review attribution (requires survey
or review platform integration) - Channel ROAS (requires ad spend
integration)

------------------------------------------------------------------------

## 6. Retention Pattern Detection

The bot does not assume the business is repeat-capable. It detects the
actual pattern from the data and applies retention logic conditionally.

### Inputs the bot computes

**Repeat purchase rate**: percentage of customer companies with more
than one closed-won deal. Computed from
`count(distinct company where count(closed-won deals) > 1) / count(distinct company where exists closed-won deal)`.

**LTV-to-AOV ratio**: average `company.total_revenue` divided by average
`deal.amount` across closed-won deals. Indicates how many transactions
per customer on average.

**Time between purchases distribution**: for repeat customers, the gaps
between consecutive `closedate` values. The bot computes median, P25,
P75. A tight distribution (e.g. consistent 6-12 month gaps) indicates
predictable repeat behaviour. A wide or sparse distribution indicates
opportunistic repeat.

**Maximum observed deal-count per company**: the highest
`num_associated_deals` (closed-won) on any single customer company.
Indicates whether power-customer behaviour exists.

**Customer cohort age**: oldest `company.createdate` on a customer
company. Indicates how much history is available to judge repeat
behaviour.

### Pattern classification

The bot classifies the client into one of four patterns, with a
confidence label:

| Pattern | Detection criteria | Confidence factors |
|:---|:---|:---|
| One-and-done | Repeat purchase rate \<15% AND LTV-to-AOV ratio \<1.3 AND maximum deal-count per company is low (typically 1-2) | High confidence when customer cohort age \>24 months and customer count \>50; low confidence on younger or smaller datasets |
| Occasional repeat | Repeat purchase rate 15-40% AND LTV-to-AOV ratio 1.3-2.0 | Same |
| Regular repeat | Repeat purchase rate 40-65% AND LTV-to-AOV ratio 2.0-4.0 AND time-between-purchases distribution is somewhat tight | Same |
| High repeat | Repeat purchase rate \>65% AND LTV-to-AOV ratio \>4.0 | Same; high-repeat patterns approach subscription-like behaviour and may warrant SaaS framework overlay |

### When detection cannot be confident

If the customer cohort is too young (\<24 months) or too small (\<50
customer companies), the bot reports detection as low-confidence and:

1.  Falls back to category metadata when available (industry hints from
    `company.industry`, configurator type, product mix).
2.  Asks the strategy team to confirm pattern based on category
    knowledge.
3.  Treats the client as occasional-repeat (the middle pattern) until
    evidence accumulates.

The bot reports the detection result and confidence level alongside any
retention-related recommendation.

### How detected pattern shifts framework application

| Pattern detected | Retention proxy (primary signal) | Recommendation emphasis | Recommendations to NOT make |
|:---|:---|:---|:---|
| One-and-done | Review submission rate, referral attribution, NPS at delivery | Maximize each transaction (AOV, quote-to-close), capture reviews, build referral motion, optimize delivery experience | Reactivation campaigns, repeat-purchase nurture sequences, win-back motion |
| Occasional repeat | Repeat purchase rate AND review/referral metrics (both meaningful) | Balanced acquisition and reactivation; capture reviews; reactivation campaigns timed to typical repeat window | Heavy automated reorder reminders (timing too unpredictable) |
| Regular repeat | Repeat purchase rate, time between purchases, dormancy rate | Reactivation campaigns timed to repeat window, repeat-purchase nurture, predictive reorder; reviews remain useful | Acquisition-only focus; ignoring dormancy signals |
| High repeat | Same as Regular repeat plus retention-style metrics | SaaS-style retention motion: account health, expansion, named account management for top customers; consider SaaS framework overlay | Pure transactional acquisition focus; ignoring expansion within accounts |

------------------------------------------------------------------------

## 7. Multi-Signal Event Detection

For each core transactional event, the bot uses primary, secondary, and
inferred signals.

### Lead (entry into the funnel)

**Primary signal**: contact created with `hs_object_source_label`
indicating an inbound entry. Pattern matching on detail values
distinguishes high-intent (Quote Request, Get Pricing, Configurator)
from low-intent (Newsletter, Resource Download).

**Secondary signal**: `first_conversion_event_name` populated.

**Cross-checks**: contacts created via IMPORT or MIGRATION often
represent existing customer data; segregate from new lead cohort.
Walk-in leads logged manually appear with Record Source = MANUAL and
require detail field discipline to track properly.

### MQL (qualified intent)

For transactional, MQL definition varies by motion. Two patterns:

**Pattern A: Quote-led**. MQL is the moment a contact requests a quote.
Detection: form submission to a quote request form OR deal created in
pipeline with stage = Quote Requested.

**Pattern B: Meeting-led** (high-consideration purchases). MQL is the
moment a sales meeting or site visit is held. Detection: meeting with
`hs_meeting_outcome` = COMPLETED.

The bot detects which pattern fits during onboarding analysis based on
whether meetings precede deals or deals precede meetings.

**Cross-checks**: contact at MQL with no associated quote request, deal,
or meeting is a lifecycle abuse signal. Treat as not MQL.

### SQL (active sales engagement)

**Primary signal**: contact is associated to at least one open deal in a
sales pipeline. SQL date is the deal’s `createdate`.

**Secondary signal**: deal at “Qualified” or equivalent stage past
initial intake.

**Cross-checks**: deal in early stage for too long (threshold scaled to
typical sales cycle for the category) is suspicious.

### Opportunity (quote sent)

**Primary signal**: deal at “Quote Sent” / “Proposal Sent” / “Pricing
Provided” or equivalent stage.

**Secondary signal**: associated quote object OR PandaDoc / DocuSign /
proposal tool activity.

**Cross-checks**: quote-stage stuck deals are common in transactional
because customers shop around; flag for follow-up.

### Customer (order closed-won)

**Primary signal**: at least one deal associated to the company where
`hs_is_closed_won` equals true AND `hs_closed_won_date` is in the past.

**Secondary signal**: company-level `total_revenue` greater than zero.

**Cross-checks**: closed-won with `hs_closed_won_date` in the future is
invalid. The bot treats the company as Customer status at the moment of
first closed-won.

### First-time vs repeat customer

**First-time**: company has exactly one closed-won deal.

**Repeat**: company has more than one closed-won deal where the deals’
close dates are separated by more than the typical sales cycle for the
category (avoiding false positives from same-cycle splits).

**Cross-checks**: when `dealtype` is populated, use it. When absent,
infer from deal count and closedate spacing. Same-cycle deals (within 60
days, similar product) should be merged for repeat-purchase analysis.
The interpretation of “repeat customer” depends on detected retention
pattern (Section 6): for one-and-done, even a few repeat customers may
be informational rather than meaningful.

### Dormancy (interpretation depends on detected pattern)

The bot computes days-since-last-purchase for every customer regardless
of pattern. The interpretation of dormancy is conditional:

- **One-and-done detected**: dormancy is the natural state. Customers
  who don’t return are not lost; they just don’t have a current need.
  The bot does not flag dormancy as risk or recommend reactivation
  campaigns.
- **Occasional repeat detected**: dormancy beyond the median
  time-between-purchases for repeat customers may indicate lapse; flag
  as recirculation candidate.
- **Regular repeat detected**: dormancy beyond P75
  time-between-purchases is a clear lapse; recommend reactivation
  campaign.
- **High repeat detected**: dormancy beyond typical interval is a strong
  risk signal; recommend immediate intervention, similar to SaaS
  health-score risk.

### Risk

**Primary signal**: stuck deal in pipeline (no stage advancement in time
appropriate to the cycle), customer service complaint logged, post-sale
issue ticket open.

**Secondary signal**: low NPS response, negative review submitted (when
review tracking is integrated).

**Cross-checks**: deal-stage health and post-purchase satisfaction are
universal risk signals regardless of retention pattern. Dormancy is risk
only when the pattern indicates repeat-capable behaviour.

------------------------------------------------------------------------

## 8. Lifecycle Model

### Canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | Marketing-only audience | Form submission to low-intent asset, no quote requests, no deals |
| Lead | Captured contact above subscriber intent | Form submission to higher-intent asset (quote, configurator, contact), inbound call logged, partner referral |
| MQL | Qualified intent (motion-dependent) | Quote requested OR meeting / site visit held with `hs_meeting_outcome` = COMPLETED |
| SQL | Active sales engagement | Open deal associated to contact in sales pipeline |
| Opportunity | Quote / proposal sent | Deal at Quote Sent / Proposal Sent stage |
| Customer | Order placed | Closed-won deal associated to contact’s company |
| Repeat customer | Subsequent order placed | Second or later closed-won deal on same company, after appropriate spacing |
| Evangelist | Multi-purchase advocate or referral source | Multiple closed-won deals OR referral attribution |

The Repeat customer and Evangelist stages exist in the canonical model
for any client, but their relevance is conditional. For a one-and-done
client, very few records will reach Repeat customer; that is expected,
not a problem.

### Mapping client-specific stages

Common mappings:

- “New Lead,” “Inquiry” map to Lead or SQL depending on whether a deal
  is created
- “Qualified,” “Hot Lead” map to SQL
- “Quote Requested,” “Quote Drafting” map to SQL or early Opportunity
- “Quote Sent,” “Pricing Provided,” “Proposal Out” map to Opportunity
- “Negotiation,” “Final Pricing” remain Opportunity
- “Order Placed,” “Won,” “Closed Won” map to Customer
- “Delivered,” “Installed,” “Completed” remain Customer plus delivery
  state (separate property recommended)
- “Lost,” “No Sale” map to closed-lost terminal state

Post-customer states (Delivered, Installed) belong in a separate
property or pipeline rather than overloading lifecycle stage.

------------------------------------------------------------------------

## 9. Business Model

**Name**: Transactional

**Inclusion rules**: - Revenue is order-based (one-time purchase, no
contractual recurrence) - Customer goes through a meaningful pre-sale
process (quote, configuration, evaluation, stakeholder coordination) -
Sales cycle ranges from days to many months depending on consideration
level - Repeat purchase happens but is not contractual or guaranteed -
Sales team is involved in most deals (not pure self-serve)

**Exclusion rules**: - Subscription-based revenue maps to SaaS
framework - Pure self-serve catalog-and-checkout maps to E-commerce
framework - Project-based delivery with consultative engagement maps to
Services framework - Two-sided supply-and-demand model maps to
Marketplace framework

**Hybrid handling**: transactional businesses with attached service
contracts (e.g. equipment plus annual maintenance) inherit from this
framework for transactions and SaaS or Services for the recurring
component. The bot computes both views and reports separately.

**Revenue trigger**: closed-won deal where `hs_is_closed_won` is true
AND deal is in a sales pipeline (not a refund or cancellation pipeline).

------------------------------------------------------------------------

## 10. Funnel and Core Events

### Funnel stages

| Stage | Detection signal |
|:---|:---|
| Entry | Contact created with Record Source = FORMS, INTEGRATION, MEETINGS, MANUAL (walk-in or phone), inbound call logged |
| Activation | Quote requested OR site visit held (motion-dependent) |
| Qualification | Open deal created in sales pipeline |
| Quote | Deal at Quote Sent / Proposal Sent stage |
| Conversion | Deal closed-won (order placed) |
| Delivery / Installation | Order delivered or installed (when tracked) |
| Repeat | Subsequent closed-won deal on existing customer (interpretation conditional on detected pattern) |

### Core events

Acquisition: new contact from a tracked source enters CRM. Activation:
qualifying signal (quote request or meeting held). Conversion: order
placed (deal closed-won). Delivery: order fulfilled. Repeat: subsequent
order on existing customer (interpretation depends on detected pattern).
Risk: stuck deal, post-sale issue, complaint.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| Acquisition | Quote / Contact / Configurator form, Record Source = FORMS | – | New Contact with `hs_object_source` populated | Inbound call logged | Partner integration write, ad platform sync |
| Activation (MQL, quote-led) | Quote request form submission | Deal stage = Quote Requested | New deal in sales pipeline | – | Configurator tool integration write |
| Activation (MQL, meeting-led) | – | – | Meeting object created | Meeting / site visit with `hs_meeting_outcome` = COMPLETED | – |
| Qualification (SQL) | – | Deal stage advances past initial | New deal in sales pipeline | – | – |
| Quote (Opportunity) | – | Deal stage = Quote Sent / Proposal Sent | Quote object created | DocuSign / PandaDoc / quote tool activity | – |
| Conversion (Customer) | – | `hs_is_closed_won` = true | New closed-won deal | – | Order management system sync |
| Delivery / Installation | – | Custom Delivery Status property changes | – | Delivery confirmation activity | Logistics integration |
| Repeat | New quote / inquiry from existing customer | – | New closed-won deal on existing customer | – | – |
| Risk | NPS detractor | Issue ticket created | Service ticket | Complaint logged | Support tool sync |

------------------------------------------------------------------------

## 11. KPI Logic

### Acquisition and Funnel

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Acquisition volume | 1 | count of contacts created | `count(contact) where createdate in [period]` | rolling 30/90 day, quarter |
| Acquisition by Record Source | 1 | count grouped by source | group by `hs_object_source_label` | requires Record Source coverage check pass |
| High-intent lead share | 1 | leads from quote / configurator / pricing forms | filter by Record Source Detail or `first_conversion_event_name` matching pattern | rolling |
| Quote requests | 1 | count of quote-pattern conversions | filter on `first_conversion_event_name` or form ID pattern | rolling |
| Lead-to-quote rate (quote-led) | 1 | quotes requested / lead cohort | numerator: contacts who submitted quote form within 90 days of createdate | 90 days from createdate |
| Lead-to-meeting rate (meeting-led) | 1 | meetings held / lead cohort | numerator: contacts whose first held meeting is within 90 days of createdate | 90 days from createdate |
| MQL-to-SQL conversion | 1 | deal-created / MQL cohort | contacts with associated open deal whose deal createdate is within 30 days of MQL event | 30 days |

### Sales

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Bookings | 1 | sum of closed-won deal value | `sum(deal.amount) where hs_is_closed_won and closedate in [period]` | rolling 30/90 day, quarter |
| Average order value | 2 | avg of closed-won deal amount | `avg(deal.amount) where hs_is_closed_won and closedate in [period]` | quarterly; requires deal amount consistency check pass |
| Win rate (cohort) | 1 | won / closed | `count(deal where hs_is_closed_won and createdate in [cohort]) / count(deal where hs_is_closed and createdate in [cohort])` | per quarter cohort, measured at appropriate horizon for the category |
| Quote-to-close rate | 2 | won / quoted | deals reaching Quote Sent stage that closed won | requires quote-stage capture check pass |
| Sales cycle | 1 | avg days create to close | `avg(deal.days_to_close) where hs_is_closed_won and closedate in [period]` | rolling |
| Stage velocity | 1 | avg time in stage | `avg(deal.hs_v2_time_in_<stageId>) where hs_date_exited_<stageId> in [period]` (default) or non-v2 (custom) | 90 day rolling |
| Pipeline value | 1 | sum of open deal value | `sum(deal.amount) where hs_is_closed = false` | live |
| Pipeline coverage | 2 | open pipeline / quarterly target | requires bookings target known | current quarter |
| Activities per rep | 1 | count by owner | `count(activity where hubspot_owner_id and hs_timestamp in [period])` | weekly |
| Closed-lost reason mix | 2 | count grouped by reason | requires closed-lost capture check pass | quarterly |

### Customer Relationship Indicators

The bot computes all of these regardless of pattern, but reports them
with conditional interpretation. See Section 6 for which become primary
signals per detected pattern.

| KPI | Tier | Formula | Schema Query | Conditional interpretation |
|:---|:---|:---|:---|:---|
| Customer count (cumulative) | 1 | distinct companies with at least one closed-won deal | `count(distinct company where exists closed-won deal)` | Universal |
| First-time customer rate | 1 | first-time customers / total customers in period | companies whose first closed-won deal closed in period | Universal |
| Repeat customer count | 1 | distinct companies with more than one closed-won deal | `count(distinct company where count(closed-won) > 1)` | Universal; interpretation depends on pattern |
| Repeat purchase rate | 2 | repeat customers / total customers | requires customer status at company level check pass | Primary signal for occasional/regular/high repeat patterns; informational only for one-and-done |
| Time between purchases (median, P25, P75) | 2 | distribution of gaps between consecutive closedates per company | requires reliable closedate values | Primary input for retention pattern detection (Section 6) |
| Average customer lifetime value | 1 | avg of `company.total_revenue` for customer companies | `avg(company.total_revenue) where company has at least one closed-won deal` | Universal |
| Lifetime value distribution | 1 | percentile distribution of `company.total_revenue` | P25, P50, P75, P95 | Universal |
| LTV-to-AOV ratio | 1 | avg LTV divided by avg order value | derived | Primary input for retention pattern detection |
| Days since last purchase per customer | 1 | today - `company.recent_deal_close_date` | live | Universal computation; interpretation depends on pattern |
| Dormancy rate | 2 | customers exceeding pattern-appropriate dormancy threshold | requires dormancy threshold per pattern | Meaningful only for occasional/regular/high repeat patterns |
| Win-back rate | 2 | dormant customers who repurchased in period / dormant pool at period start | requires dormancy tracking | Meaningful only for occasional/regular/high repeat patterns |
| Referral attribution | 3 | leads or customers attributed to existing customer referrals | requires referral tracking infrastructure | Primary signal for one-and-done; useful for all patterns |
| Review submission rate | 3 | reviews submitted / orders | requires review platform integration | Primary signal for one-and-done; useful for all patterns |

### Service / Post-Sale (Tier 3 unless noted)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| Time-to-delivery | 3 | avg of delivery date - close date | Delivery date tracking |
| Time-to-installation | 3 | avg of installation date - close date | Installation tracking |
| Warranty claim rate | 3 | warranty tickets / orders delivered | Service ticket integration with order linkage |
| NPS | 3 | survey-based | Survey integration |
| Customer satisfaction at delivery | 3 | survey at delivery checkpoint | Delivery survey integration |

------------------------------------------------------------------------

## 12. Order Value-Based Personalization

The bot adjusts recommendations based on average order value, retention
pattern, and cycle length. AOV and cycle length apply universally;
retention pattern is conditional per detection (Section 6).

### What the bot looks up per client

**Median order value**: median of `deal.amount` across closed-won deals
in trailing 12 months.

**Order value distribution**: P25, P50, P75, P95.

**Detected retention pattern**: per Section 6.

**Sales cycle distribution**: median, P25, P75 of `deal.days_to_close`.
Distinguishes fast cycle (median \<14 days) from slow cycle (median \>60
days).

**Top-10 customer concentration**: % of trailing 12-month bookings from
top 10 customers. High concentration indicates B2B-style enterprise
transactional with key accounts.

### Order value bands

| Band | AOV Range | Motion | Recommendation emphasis (universal across patterns) |
|:---|:---|:---|:---|
| Low | \<\$500 | High volume, marketing-led, fast cycle | Marketing automation, attribution, AOV optimization, low-touch sales process |
| Medium | \$500 - \$5K | Quote-led inside sales, medium cycle | Pipeline volume, speed-to-quote, quote-to-close conversion, lead routing |
| Considered | \$5K - \$50K | Full-cycle sales, multi-stakeholder common | Quote-stage discipline, stakeholder mapping, follow-up cadences, formal proposal infrastructure |
| High | \$50K - \$500K | Complex sale, financing or procurement involved | Account-based, multi-threading, formal proposal and contract management, executive sponsorship |
| Capital | \$500K+ | Strategic capital purchase | Bespoke proposal, executive sponsorship, technical evaluation, financing partnerships |

### Conditional retention emphasis (layered on top of AOV band)

The bot adds retention-pattern-specific recommendations on top of AOV
band:

- **One-and-done detected**: emphasize review and referral capture, NPS
  at delivery, customer experience optimization, AOV maximization on
  each transaction. Do not recommend reactivation campaigns or
  repeat-purchase nurture.
- **Occasional repeat detected**: balance acquisition and reactivation.
  Time reactivation campaigns to median time-between-purchases. Reviews
  and referrals remain valuable.
- **Regular repeat detected**: emphasize reactivation campaigns,
  repeat-purchase nurture, predictive reorder timing. Reviews secondary.
- **High repeat detected**: SaaS-style retention motion (account health,
  expansion, named account management for top customers). Consider
  applying SaaS framework overlay.

### Cycle length

Fast cycle businesses need automation, speed-to-lead, and high-volume
pipeline management. Slow cycle businesses need stakeholder mapping,
multi-touch nurture, and formal pipeline review processes. The bot
adjusts recommendation priority accordingly, independent of retention
pattern.

### Top-10 concentration

High concentration (\>60%) indicates effectively enterprise
transactional regardless of median AOV; the bot weights toward
enterprise-tier infrastructure (account management, multi-stakeholder
selling, executive engagement) regardless of detected retention pattern.

------------------------------------------------------------------------

## 13. Benchmarks

Transactional benchmarks vary enormously by category. AOV band, cycle
length, and detected retention pattern drive most variance. Replace with
Blu’s authoritative benchmarks when ingested.

### Acquisition and Top of Funnel (universal)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Lead-to-quote rate (quote-led motion) | \>35% | 20-35% | \<20% | High-intent forms self-select |
| Lead-to-meeting rate (high-consideration) | \>25% | 15-25% | \<15% |  |
| Quote-to-close conversion | \>30% | 15-30% | \<15% |  |
| MQL-to-SQL conversion | \>60% | 40-60% | \<40% |  |
| Cost per quote (paid channels) | varies by AOV; track trend | – | – |  |
| Speed to lead (inbound quote request) | \<30 min | 30 min - 2 hr | \>2 hr |  |
| DQ rate | \<20% | 20-35% | \>35% |  |

### Sales (universal)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Win rate (cohort) | 25-45% | 15-25% | \<15% | Wide range due to category variance |
| Sales cycle (low AOV / fast cycle) | \<14d | 14-30d | \>30d |  |
| Sales cycle (medium AOV) | 14-45d | 45-90d | \>90d |  |
| Sales cycle (considered AOV) | 45-90d | 90-150d | \>150d |  |
| Sales cycle (high / capital AOV) | 90-180d | 180-365d | \>365d |  |
| Pipeline coverage | 3-4x | 2-3x | \<2x | Tighter for fast-cycle products |
| Activity per rep per day | 30-60 | 15-30 | \<15 | Inbound-heavy roles lower |
| Quote-stage stuck deals | \<15% of quote-stage open pipeline \>30 days | 15-25% | \>25% | Quote follow-up discipline indicator |

### Customer Relationship Indicators (conditional thresholds per detected pattern)

Repeat purchase rate benchmarks apply only when retention pattern is
occasional repeat or stronger. For one-and-done detected, repeat
purchase rate is informational and has no alarm threshold.

| Metric | Pattern | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|:---|
| Repeat purchase rate | One-and-done | – | – | – | Informational; low repeat is expected |
| Repeat purchase rate | Occasional repeat | \>25% | 15-25% | \<15% |  |
| Repeat purchase rate | Regular repeat | \>50% | 30-50% | \<30% |  |
| Repeat purchase rate | High repeat | \>65% | 50-65% | \<50% |  |
| Win-back rate (campaigns to dormant pool) | Occasional / Regular / High repeat | \>5% per quarter | 2-5% | \<2% | When formal win-back motion exists; not applicable to one-and-done |
| Time-between-purchases consistency (P75 / median ratio) | Regular / High repeat | \<2.0 | 2.0-3.0 | \>3.0 | Tighter ratio indicates predictable behaviour; useful for predictive reorder |
| Referral share of new customers | All patterns; primary for one-and-done | \>20% | 10-20% | \<10% | Strong referral share indicates brand strength |
| Review submission rate (when integrated) | All patterns; primary for one-and-done | \>25% of orders | 10-25% | \<10% | Critical for one-and-done; useful for all |
| Negative review rate | All patterns | \<5% of submitted | 5-10% | \>10% |  |
| LTV-to-AOV ratio | All patterns | track trend; band identifies pattern | – | – | Used as input to pattern detection, not as a benchmark itself |

### Post-Sale (universal)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|----|
| Time-to-delivery (against commitment) | within commitment | 0-25% over | \>25% over |  |
| Warranty claim rate (durable goods) | \<3% of orders | 3-8% | \>8% | Category-dependent |
| NPS | \>40 | 20-40 | \<20 | Transactional NPS varies by category |

### Maturity stage adjustments

| Stage | Revenue range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Founder / Local | \<\$2M | Lead generation, conversion basics, owner-led sales | Loose benchmarks; informal pipeline; manual processes |
| Growth | \$2M - \$10M | Pipeline structure, attribution, basic CRM hygiene | Standard benchmarks; first formal pipeline and reporting |
| Scale | \$10M - \$50M | Multi-channel attribution, lifecycle marketing, conditional retention motion (per detected pattern), segmentation | Tighter benchmarks; structured comp |
| Established | \$50M+ | Account-based segmentation, key account management, multi-region or multi-product complexity, margin discipline | Enterprise transactional benchmarks |

The Revenue Stack Diagnostic order for transactional adapts based on
retention pattern detected:

- One-and-done: lead volume and conversion first, AOV and cycle
  efficiency second, review and referral capture third.
- Occasional / Regular / High repeat: lead volume and conversion first
  at founder/local stage; repeat customer rate, dormancy, and win-back
  motion increasingly important at Scale and Established.

------------------------------------------------------------------------

## 14. Required Data Minimum

**Identity**: email plus company domain. For consumer-leaning
transactional, email plus phone may substitute when company is not
applicable.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate`, meeting `hs_timestamp` (when meetings are part of motion),
deal stage history.

**Revenue value**: `deal.amount` populated on closed-won deals with
consistent magnitude convention. Critical floor.

**Activity / engagement signal**: at least one of
`notes_last_contacted`, `last_activity_date`, `last_engagement_date`
populated.

**Owner**: `hubspot_owner_id` populated on at least 80% of customer-tier
records, mapped to active users.

**Customer status at company level**: `lifecyclestage` set to Customer
on at least 85% of companies with associated closed-won deals.

**Quote stage capture**: a distinct “Quote Sent” / “Proposal Sent” /
“Pricing Provided” stage exists in the sales pipeline.

**For confident retention pattern detection**: customer cohort age \>24
months OR more than 50 customer companies with closed-won deals tracked.
When this floor is missed, the bot reports retention pattern detection
as low-confidence and recommends conservative interpretation (treat as
occasional repeat as default).

When any required floor is missed, the bot reports the gap as the
highest-priority finding before analyzing anything else.

------------------------------------------------------------------------

## 15. Rules and Edge Cases

### What happens when each event occurs

**Acquisition**: Record Source captured automatically, lifecycle
workflow may set Subscriber or Lead, owner assigned per routing rules,
sequence enrolment for nurture.

**Activation (MQL)**: quote requested or meeting held, lifecycle
workflow may set MQL (cross-validated by bot), AE notified, follow-up
cadence triggered.

**Qualification (SQL)**: deal created, owner assigned, qualification
workflow.

**Quote (Opportunity)**: deal advances to Quote Sent stage, quote
document generated and sent, automated follow-up reminder if not closed
within X days for the category.

**Conversion (Customer)**: deal closes won, lifecycle workflow sets
Customer at company level, post-sale fulfillment process triggered,
delivery scheduling, warranty registration if applicable, review/NPS
request triggered (especially important for one-and-done detected
pattern).

**Repeat purchase**: new closed-won deal on existing customer,
attribution to triggering signal. Interpretation conditional on detected
pattern: meaningful retention event for repeat-capable patterns;
pleasant surprise for one-and-done.

**Dormancy threshold passed**: action conditional on detected pattern.
For repeat-capable patterns, customer flagged on dormant list, eligible
for re-engagement campaigns. For one-and-done, no flag; dormancy is the
default state.

**Risk / complaint**: alert to owner or service team, ticket created,
resolution tracked. Universal across patterns.

### Duplicate handling

- Contacts: dedupe by email primary, secondary by phone for B2C-leaning
  businesses, secondary by company domain plus name for B2B.
- Companies: dedupe by domain primary, secondary by name plus location.
- Deals: same-cycle deals (within 60 days, same company, similar
  product) should be merged or associated; the bot flags suspected
  same-cycle splits where one order was entered as multiple deals.

### Missing signals

- No Record Source captured (pre-Feb 2024 records): use
  `hs_analytics_source` as fallback with reduced confidence.
- No company associated (B2C-leaning record): operate at contact level
  for that record.
- No deal value at close: flag for review, exclude from AOV and bookings
  rollup.
- No closed-lost reason: flag for capture process improvement.
- No quote stage in pipeline: recommend adding one.
- No customer-level lifecycle setting: recommend workflow that sets
  `company.lifecyclestage` = Customer when first associated deal closes
  won.
- Insufficient deal history for pattern detection: report low-confidence
  detection and treat as occasional repeat by default.

### Out-of-order events

- Customer status before any deal: lifecycle abuse, not real customer
  status. Do not count.
- Closed-won with `hs_closed_won_date` in the future: invalid.
- Multiple closed-won in rapid succession on same company: probable
  same-cycle split; merge for repeat purchase analysis.
- Win-back without prior dormancy: company was never tagged dormant
  before repurchasing; backfill the dormancy event from
  `recent_deal_close_date` history.

### Source conflicts

Same as other frameworks. Record Source primary; Analytics Source
secondary; trust Record Source on conflict. For transactional, partner
referrals, walk-in (MANUAL), and inbound phone (logged manually) often
blur attribution. Recommend explicit Lead Source or Channel custom
property to reduce ambiguity.

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
5.  Apply detected retention pattern to interpret all retention-related
    metrics conditionally.

Example output structure for a residential construction transactional
business:

    Account: Example Construction Co
    Pre-flight findings:
      Customer status at company level: ALARM (52% of companies with closed-won deals
        are not at Customer lifecycle)
      Deal amount consistency: HEALTHY
      Record Source coverage: WATCH (76%, mostly pre-Feb 2024 records)
      Quote-stage capture: HEALTHY
      Sufficient deal history for pattern detection: HEALTHY (47-month customer cohort,
        847 customer companies)

    Retention pattern detected:
      Pattern: One-and-done
      Confidence: HIGH
      Repeat purchase rate observed: 18.4% (informational; low repeat is expected for
        this pattern)
      LTV-to-AOV ratio: 1.5
      Median time between purchases (when it occurs): 4.2 years (sparse, opportunistic)
      Implication: retention motion focuses on review/referral capture; reactivation
        campaigns are not recommended

    Top recommendations:
      1. Build workflow: when company has first closed-won deal, set
         company.lifecyclestage to Customer.
      2. Attribution improvement: 24% of contacts lack Record Source. Recommend custom
         Lead Source property with workflow population.
      3. Review and referral capture: implement post-delivery NPS and review request
         workflow. Detected one-and-done pattern means social proof drives the next
         deal more than repeat-purchase nurture would.

    Reliable metrics (Tier 1):
      Bookings: $4.2M last quarter
      Average order value: $34K
      Pipeline value: $11.8M open
      Pipeline coverage: 2.8x (WATCH)
      Win rate: 28% on cohort closed in last quarter
      Quote-to-close rate: 41% (HEALTHY)
      Sales cycle: 67 days
      Customer count (cumulative): 847
      Customer lifetime value (avg): $51K
      LTV / AOV ratio: 1.5

    Conditional metrics (interpretation per detected pattern):
      Repeat purchase rate: 18.4% (informational only; one-and-done detected)
      Days since last purchase: average 31 months (consistent with one-and-done)
      Dormancy: not flagged as risk (one-and-done detected)

    Gap-flagged metrics (Tier 3):
      Time-to-installation: cannot compute. No installation date tracking detected.
      NPS / Review attribution: cannot compute. No survey or review platform integration.
        PRIORITIZED gap given detected one-and-done pattern.

    Order value personalization applied:
      Median order value: $34K (Considered band)
      P25-P75 range: $18K to $58K
      Detected retention pattern: One-and-done
      Top-10 customer concentration: 22% (no enterprise concentration)
      Diagnostic priority: Lifecycle data hygiene, then attribution coverage, then
        review/referral infrastructure (per detected pattern).

------------------------------------------------------------------------

End of Transactional framework.
"""
