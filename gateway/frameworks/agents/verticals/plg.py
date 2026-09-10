from ..base import BaseAgent


class PLGAgent(BaseAgent):
    """PLG vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered PLG framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised PLG framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "plg"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: PLG (Product-Led Growth)

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Compute baseline metrics from
validated standard fields. Custom properties, integrations, and product
event syncs are enrichments.

**The product database is the source of truth, not HubSpot.** Signup
events, activation events, feature usage, plan changes, and login
frequency all live in the product or a product analytics system
(Segment, Mixpanel, Amplitude, Heap, custom database). HubSpot is the
marketing and sales overlay that consumes product event data via
integration. Integration health is the single most important data
quality factor for this vertical.

**Trust events, not statuses.** The bot derives stage from underlying
events: signup, activation, product usage thresholds, plan upgrade, paid
conversion. Lifecycle stage values are validated against event truth.

**Record Source over Analytics Source.** `hs_object_source` is set at
creation and not editable in most cases. For PLG, contacts created from
product signups typically arrive via INTEGRATION with the product
platform name in detail fields. `hs_analytics_source` became editable in
2024.

**Detect motion type, do not assume it.** PLG ranges from pure
self-serve (no sales involvement at any price tier) to sales-assisted
PLG (self-serve for individual and team, sales for enterprise) to hybrid
(substantial traditional sales motion alongside PLG). Each requires
different framework emphasis. The bot observes whether sales reps are
involved in deals, the share of revenue from sales-touched deals, and
the presence of enterprise pipeline before applying recommendations.

**Detect free model and expansion model.** Time-bound trial, freemium
with feature limits, freemium with usage limits, and free-forever models
behave differently. Per-seat expansion, tier-based expansion, and
usage-based expansion produce different recommendation priorities.

**Detect retention pattern.** PLG has subscription-style retention by
definition (recurring revenue once paid), but free-tier behaviour varies
enormously: some products have churnful free tiers (users sign up and
disappear), others have sticky free tiers (users return monthly). The
bot observes both free-tier and paid-tier retention patterns separately.

**Validate before trusting.** Pre-flight reliability checks gate every
metric, with product data integration health as the first concern.

------------------------------------------------------------------------

## 1. Category Definition

PLG businesses use the product itself as the primary acquisition,
activation, and expansion engine. Customers sign up, use the product
(often free or trial), and convert to paid through in-product experience
or sales-assisted handoff. Includes individual-productivity tools,
collaboration tools, developer tools, and self-serve B2B applications
that adopt freemium or trial models. Famous examples include Slack,
Notion, Figma, Linear, Calendly, Loom, and Dropbox.

Distinct from sales-led SaaS because the first paid conversion happens
without sales involvement in most cases. Distinct from E-commerce
because the product is software with subscription revenue. Distinct from
Marketplace because the platform is single-sided (the company sells to
its users directly).

Hybrid cases are common and should be acknowledged. Sales-assisted PLG
is the dominant pattern at enterprise scale: pure self-serve for
individuals and small teams, sales engagement for larger contracts. The
bot detects motion type and applies appropriate framework emphasis. A
SaaS company with a small PLG side-motion (free trial that mostly
funnels to demo requests) is more SaaS than PLG and should be evaluated
under the SaaS framework with PLG overlay.

## 2. Common GTM Motion

Marketing drives traffic to the signup page through content, SEO, paid
acquisition, community, virality, or developer evangelism. Signup is
self-serve, typically requiring only email and password (or SSO).

Activation is the critical first product moment: the user does something
meaningful with the product within their first session or first few
sessions. The activation event is product-specific (sent first message,
created first document, made first API call, invited first teammate) but
has universal funnel weight: users who never activate almost never
convert.

Conversion to paid happens through in-product experience: paywall
encounters, feature limit hits, trial expiration, or upgrade prompts.
The customer self-serves through checkout. For sales-assisted PLG,
high-engagement free or trial users get flagged as PQLs (Product
Qualified Leads) and routed to sales for enterprise deals or larger
contracts.

Expansion is the largest revenue driver at scale. Three expansion models
dominate: - Per-seat: more team members invited and added to the paid
plan - Per-tier: upgrade from Basic to Pro to Enterprise based on
feature need - Usage-based: consumption growth (API calls, storage,
transactions)

Customer success motion exists for enterprise tier and high-value
accounts; lower tiers typically receive automated lifecycle email and
in-product nudges.

## 3. KPIs by Function

### Marketing

Signups, cost per signup, signup channel mix, content-to-signup
attribution, organic vs paid signup share, virality coefficient (users
who invite other users), waitlist conversion, demo or contact-sales
requests (sales-assisted overlay).

### Product / Activation

Activation rate, time-to-activation, day-1, day-7, day-30 retention
curves, feature adoption rate, NPS, product engagement intensity per
cohort.

### Conversion

Free-to-paid conversion rate, trial-to-paid conversion rate, conversion
timing distribution, PQL volume (sales-assisted), PQL-to-paid rate.

### Sales (when sales-assisted)

PQL volume routed to sales, sales-assisted deal volume, sales-touched
deal value, win rate on sales-assisted deals, sales cycle for
sales-assisted deals.

### Customer Success / Retention

Gross Revenue Retention, Net Revenue Retention, logo churn, revenue
churn, expansion revenue (per-seat, per-tier, usage), expansion rate,
customer health score distribution, time to expansion, contraction rate.

### Free-tier health

Active free user count, free-user engagement (DAU/WAU/MAU ratios),
free-tier retention curves, free-tier conversion timing.

The relative weight of these depends on detected motion type and
free/expansion models, addressed in Sections 6 and 13.

------------------------------------------------------------------------

## 4. HubSpot Schema Foundation

Property names verified against HubSpot’s official documentation as
standard.

### Contact (always present)

**Identity and ownership**: `createdate`, `hubspot_owner_id`,
`hubspot_owner_assigneddate`, `hs_marketable_status`, `hs_lead_status`,
`lifecyclestage`.

**Record Source (primary attribution)**: `hs_object_source`,
`hs_object_source_label`, `hs_object_source_detail_1`,
`hs_object_source_detail_2`, `hs_object_source_detail_3`. For PLG,
contacts most commonly arrive via INTEGRATION (when product signup syncs
to HubSpot) with the product’s identifier in the detail field. The bot
identifies the product integration during onboarding analysis and uses
Record Source pattern matching to confirm product-sourced contacts.

**Analytics Source (secondary)**: `hs_analytics_source` and related
fields.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`. For PLG, first conversion type often
distinguishes signup-driven contacts (form name matches signup or trial
pattern) from marketing-content contacts (form name matches resource or
webinar pattern). This distinction matters because signup-driven
contacts have already entered the product funnel.

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open`, `hs_email_click`,
`hs_sales_email_last_opened`, `hs_sales_email_last_clicked`,
`hs_sales_email_last_replied`, `hs_email_sends_since_last_engagement`.

**Deal association**: `num_associated_deals`. For PLG, deals typically
represent paid conversions or sales-assisted deals. Self-serve free
users do not have associated deals until they convert.

### Company (always present)

`createdate`, `hubspot_owner_id`, `num_associated_contacts`,
`num_associated_deals`, `recent_deal_amount`, `recent_deal_close_date`,
`total_revenue`, `last_activity_date`, `lifecyclestage`, `industry`,
`numberofemployees`, `annualrevenue`, `hs_object_source`,
`hs_object_source_label`.

For B2B PLG, accounts often emerge bottom-up: individual users sign up,
then teammates join, eventually the company (domain) accumulates enough
users to become an enterprise opportunity. The bot uses email domain to
associate contacts to companies and tracks user count per domain as a
leading expansion indicator.

### Deal (always present, but used inconsistently across PLG HubSpots)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype` (newbusiness, existingbusiness), `hubspot_owner_id`,
`num_associated_contacts`.

**SaaS revenue properties**: `hs_arr`, `hs_mrr`, `hs_acv`, `hs_tcv`.
These are calculated from associated recurring line items and require
Sales Hub Professional or Enterprise. For PLG, when self-serve
subscriptions sync as deals with line items, these properties populate.
When subscriptions live only in the billing system (Stripe, Chargebee,
Maxio), they do not populate in HubSpot and the bot relies on
integration custom properties.

**Close state**: `hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`, `hs_closed_won_date`, `closed_lost_reason`,
`days_to_close`.

**Stage history**: `hs_date_entered_<stageId>`, `hs_v2_*` versions.

In PLG HubSpots, deals can mean different things: - Self-serve paid
conversion deals (often synced from billing system, immediately
closed-won) - Sales-assisted deals (BD pipeline, multi-stage, typical
sales motion) - Expansion deals (upsell, seat additions, tier upgrades)

The bot identifies which deal models are in use during onboarding
analysis.

### Activity

Standard schema. Activity volume in pure PLG is light (most users never
interact with sales). Sales-assisted PLG has higher activity volume on
PQL-routed contacts.

### Custom integration properties

PLG HubSpots typically have product-event custom properties created by
integration:

- Signup date (often distinct from `createdate` if contact existed
  before product signup)
- Activation date (when activation event fired)
- Last login date
- Total logins or sessions
- Plan tier (Free, Pro, Team, Enterprise, etc.)
- Plan started date
- MRR / ARR per contact or per company (sometimes)
- Active users in workspace (for collaboration tools)
- Feature adoption flags

The bot identifies these during onboarding analysis. They are typically
the most important enrichments for PLG because the product engagement
signals they carry are the foundation of PQL detection and activation
analysis.

### What the bot derives from standard schema

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source | `contact.hs_object_source_label` and detail fields |
| Product signup vs marketing signup | `contact.first_conversion_event_name` plus Record Source Detail |
| Engagement recency | `last_engagement_date`, `last_activity_date`, email engagement dates |
| Paid conversion | first associated closed-won deal |
| Time to paid conversion | days from `createdate` to first closed-won deal |
| Self-serve vs sales-assisted | deal pipeline membership, presence of sales activities, deal owner identity |
| Account-level expansion (B2B PLG) | growth in `company.num_associated_contacts` and additional closed-won deals |
| Company lifetime value | `company.total_revenue` |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: PLG HubSpots have specific failure patterns
rooted in product-data integration depth.

### Properties to treat as unreliable by default

**Lifecycle stage.** Editable, frequently misused. PLG-specific failure:
every product signup gets set to Customer lifecycle (because they “have
an account”), conflating free users with paying customers. Or,
alternatively, every signup gets stuck at Lead because no workflow
advances them through the funnel. The bot derives lifecycle from events.

**Analytics source.** Editable since 2024.

**Free vs paid distinction.** Many PLG HubSpots do not clearly
distinguish free users from paid customers in HubSpot. If lifecycle is
set to Customer for all signups, or if deals are not created for paid
conversions, the bot cannot reliably identify paying customers. This is
the most common and most consequential PLG HubSpot data issue.

**Product usage data.** When integrated via Segment, custom sync, or
product analytics platform, the data may be stale, sparse, or
incomplete. The bot validates freshness and population.

**Deal amount.** When self-serve paid conversions create deals via
billing system sync, amount handling varies. Some clients sync monthly
recurring value; others annual; others total contract value. Some
include tax, others don’t. The bot validates magnitude and flags mixed
conventions.

**Plan tier property.** When custom-built, this property’s options often
drift over time as the product adds and renames tiers. Old contacts may
have outdated tier values that no longer exist in the current schema.

### Properties to trust by default

Record Source, object timestamps (especially `createdate`), boolean
state flags (`hs_is_closed*`), engagement recency, integration property
updates from healthy syncs.

### Pre-flight reliability checks

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Product integration health | last sync time, signup count vs product database, activation event freshness | recent and aligned | sync delayed or count drift | broken or counts diverging \>10% | All product-event metrics, PQL detection, activation analysis |
| Free vs paid distinction | clear separation of free users (signed up, no closed-won) from paid customers (closed-won deal) via lifecycle, plan property, or other reliable signal | yes, \>90% accurate | partial | absent or widely incorrect | All paid customer metrics, free-to-paid conversion, NRR/GRR |
| Activation event capture | activation event property populated for active product users in last 30 days | populated | sparse | absent | Activation rate, time-to-activation, activation-to-paid funnel |
| Plan tier reliability | plan tier property populated and aligned with current product schema | aligned and populated | partial | mismatched or absent | Tier-based segmentation, upgrade analysis |
| Customer status consistency | % of contacts (or companies for B2B PLG) with closed-won deals correctly tagged as Customer | \>85% | 60-85% | \<60% | Customer count, retention metrics |
| Deal amount consistency | variance and pattern of `deal.amount` magnitude | manageable | suspect mixing | mixed conventions | All revenue metrics |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source-level analysis (lower threshold for accounts pre-Feb 2024) |
| Sales motion detection | clear identification of sales-assisted vs self-serve deals (via pipeline, owner, or property) | clear | partial | mixed | Motion-specific analysis |
| Sufficient cohort age for retention pattern detection | paid customer cohort age \>12 months OR more than 200 paid customers | yes | partial | absent | Retention pattern detection |
| Free-tier engagement signal | last login date or session count populated for active free users | populated | sparse | absent | Free-tier health, PQL detection |

### Confidence tiers for PLG metrics

**Tier 1 (high confidence, computable from validated standard
schema)**: - Contact (signup) volume by Record Source - Acquisition
channel mix - Email engagement metrics - Activity volume (where
relevant) - Paid customer count (when free vs paid distinction is
reliable) - Deal volume (closed-won) - Bookings / paid conversion
volume - Sales cycle for sales-assisted deals

**Tier 2 (medium confidence, requires reliability check pass)**: - AOV /
ACV (requires deal amount consistency) - Free-to-paid conversion rate
(requires free vs paid distinction) - Sales-assisted deal mix (requires
sales motion detection) - Source-level conversion (requires Record
Source coverage) - Repeat / expansion rate (requires customer status
consistency)

**Tier 3 (requires custom infrastructure or product integration
depth)**: - Activation rate, time-to-activation (requires activation
event integration) - Day-1 / Day-7 / Day-30 retention curves (requires
session data integration) - PQL volume and PQL-to-paid rate (requires
PQL definition implemented) - NRR / GRR (requires renewal infrastructure
plus point-in-time ARR snapshots) - Per-seat or per-tier expansion rate
(requires plan tier and seat count tracking) - Usage-based expansion
rate (requires usage data integration) - Feature adoption rate (requires
product event integration) - Customer health scoring (requires
functional health score with active update) - Virality coefficient
(requires invite event tracking)

------------------------------------------------------------------------

## 6. Motion Detection

PLG ranges across a spectrum from pure self-serve to heavily
sales-assisted. The bot detects motion type from observable signals
before applying recommendations.

### Motion types

**Pure self-serve PLG**: no sales reps involved at any price tier. All
conversions happen in-product through self-serve checkout. Customer
success may be present for enterprise tier but sales is not. Examples:
most consumer-prosumer tools, low-ACV B2B utilities.

**Sales-assisted PLG**: self-serve handles individual and small team
plans; sales engages for larger team plans, enterprise contracts, custom
deals. Most modern B2B PLG companies operate this way once they reach
scale. Examples: Slack, Notion, Figma, Linear at enterprise scale.

**Hybrid PLG-and-Sales**: substantial sales motion alongside PLG. The
PLG funnel feeds sales as a primary lead generation channel; many deals
close through sales-led process even when the user could have
self-served. Border with traditional SaaS.

**SaaS with PLG side-motion**: predominantly sales-led SaaS with a free
trial or freemium tier as a marketing tool. Should be evaluated under
SaaS framework primarily; PLG framework provides overlay for the trial
portion.

### Detection signals

The bot computes:

**Sales activity share on conversions**: % of closed-won deals
associated with at least one logged sales activity (call, meeting,
sales-tracked email) within 60 days before close. Low share indicates
self-serve dominance.

**Sales-led deal pipeline existence**: distinct sales pipeline with
multi-stage progression vs single-stage “Customer” pipeline that just
records billing events.

**Sales-assisted deal value share**: % of total bookings from deals with
sales activity. Indicates economic weight of sales motion.

**Owner identity on deals**: deals owned by sales reps vs deals with no
owner or with system-account owners. Self-serve conversions typically
have no owner or a generic owner.

**Time from signup to first sales touch**: days from
`contact.createdate` to first logged sales activity. Long times (or no
touch at all) indicate the user converted before sales engagement.

### Classification

| Motion type | Sales activity share on conversions | Sales-assisted deal value share | Pipeline structure |
|:---|:---|:---|:---|
| Pure self-serve | \<10% | \<10% | Single-stage closed-won pipeline or no pipeline |
| Sales-assisted PLG | 20-50% | 30-70% | Distinct sales pipeline; PLG conversions outside sales pipeline |
| Hybrid PLG-and-Sales | 50-80% | 60-90% | Substantial sales pipeline; PLG feeds sales |
| SaaS with PLG side-motion | \>80% | \>90% | Predominant sales pipeline; PLG is acquisition tactic |

### How motion type shifts framework application

| Motion | Framework emphasis | Recommendations to NOT make |
|:---|:---|:---|
| Pure self-serve | Activation rate optimization, free-to-paid conversion timing, in-product upgrade prompts, lifecycle email, expansion via in-product nudges | Pipeline coverage analysis, AE quota recommendations, sales-led pipeline structure |
| Sales-assisted PLG | Both PLG funnel optimization (signup-to-activation-to-paid) and sales-assisted pipeline (PQL-to-sales-to-close); split analytics by motion | Treating all conversions as one funnel; recommending sales structure for self-serve tier |
| Hybrid PLG-and-Sales | Full SaaS framework with PLG overlay for top-of-funnel | Treating as pure PLG; underestimating sales process needs |
| SaaS with PLG side-motion | Apply SaaS framework as primary; use PLG framework only to evaluate trial conversion mechanics | Over-investing PLG infrastructure when sales is the real engine |

------------------------------------------------------------------------

## 7. Free-Tier and Expansion Model Detection

In addition to motion type, the bot detects two more conditional
dimensions.

### Free model

The bot identifies the free model by examining signup-to-paid conversion
timing and free-tier engagement patterns:

- **Time-bound trial** (typically 14 or 30 days): conversion timing
  distribution is clustered around trial expiration; users who don’t
  convert within trial period rarely convert later. Free users
  essentially don’t exist long-term.
- **Freemium with feature limits**: users can stay free indefinitely but
  encounter feature paywalls. Conversion timing is dispersed; some users
  convert in week 1, others in year 2 when they need a gated feature.
- **Freemium with usage limits**: similar to feature limits but with
  metered consumption (e.g. number of documents, API calls). Conversion
  correlates with usage growth.
- **Free-forever (no upgrade path)**: most users will never convert;
  small minority does. Common in developer tools and consumer products.

### Expansion model

Detected from how revenue grows per account:

- **Per-seat expansion**: ARR per company correlates with seat count or
  `company.num_associated_contacts`. Slack, Notion, Figma pattern.
- **Per-tier expansion**: customers upgrade plan tiers (Basic to Pro to
  Enterprise). ARR per company shows step changes corresponding to tier
  upgrades. Recurring vs additional plan property changes.
- **Usage-based expansion**: ARR per company correlates with consumption
  metric (API calls, transactions, storage). Often less predictable;
  expansion happens through volume invoices.
- **Hybrid**: combinations of the above (typical at enterprise scale).

### Recommendation emphasis by free model and expansion model

| Free model | Recommendation emphasis |
|:---|:---|
| Time-bound trial | Trial-period activation optimization, day-7 and day-12 in-trial nudges, trial-expiration upgrade flow, trial extension policy |
| Freemium feature limits | Feature paywall encounter rate, feature-limit upgrade conversion, in-product upgrade prompt at moments of value |
| Freemium usage limits | Usage tracking and alert infrastructure, usage-based upgrade prompts, soft limits with grace |
| Free-forever | Volume play; marketing focus on top-of-funnel; conversion is opportunistic |

| Expansion model | Recommendation emphasis |
|:---|:---|
| Per-seat | Team-invite virality, seat tracking and reporting, per-seat pricing optimization, account-level CSM engagement |
| Per-tier | In-product feature gating clarity, upgrade-prompt placement, tier value differentiation, sales-assisted upgrade for high tiers |
| Usage-based | Usage transparency tools, predictive usage alerts, customer success engagement on consumption patterns, true-up vs metered billing |
| Hybrid | Multiple expansion vectors tracked separately; segmented recommendations per dominant vector |

------------------------------------------------------------------------

## 8. Multi-Signal Event Detection

### Signup (entry into the product funnel)

**Primary signal**: contact created with `hs_object_source_label`
indicating product signup (typically INTEGRATION with product platform
identifier, or FORMS with signup-pattern form name).

**Secondary signal**: `first_conversion_event_name` matches signup
pattern; signup-specific custom property (e.g. `signup_date`) populated.

**Cross-checks**: contacts created via marketing forms (whitepaper,
webinar) without product signup are not in the product funnel; they are
marketing leads. The bot distinguishes these to avoid inflating signup
metrics.

### Activation

**Primary signal**: activation event property populated (custom property
created by product integration) OR activation event in product analytics
platform.

**Secondary signal**: meaningful product engagement signals (multiple
sessions, feature usage flags) when activation property is not directly
tracked.

**Cross-checks**: when activation tracking is absent, the bot reports
activation metrics as Tier 3 gap and recommends the integration build.
Without activation, PLG analysis is fundamentally limited.

### PQL (sales-assisted PLG only)

**Primary signal**: contact meets PQL criteria as defined in client’s
HubSpot (custom property, list membership, scoring threshold).

**Secondary signal**: contacts with high product engagement signals from
custom domain or with multiple users at the same domain (B2B PLG).

**Cross-checks**: PQL definition varies enormously across clients. The
bot identifies the client’s PQL definition during onboarding analysis.
When no formal PQL definition exists in a sales-assisted PLG context,
the bot reports this as a gap and recommends defining PQL based on
observable behavioural and firmographic signals.

### Paid conversion

**Primary signal**: first associated closed-won deal where
`hs_is_closed_won` is true. For self-serve, this deal was created by
billing integration when the user converted. For sales-assisted, this
deal closed through a sales pipeline.

**Secondary signal**: plan tier property changes from free to paid
value.

**Cross-checks**: when a user appears at Customer lifecycle but no
closed-won deal exists, this is lifecycle abuse OR billing integration
gap. When a closed-won deal exists with no associated paid contact, this
is association issue. The bot validates and flags.

### Expansion

**Primary signal**: depending on detected expansion model: - Per-seat:
increase in `company.num_associated_contacts` correlates with
company-level ARR increase, OR new closed-won deal in expansion or
upsell pipeline - Per-tier: plan tier property changes to higher tier -
Usage-based: usage property increase plus billing change

**Secondary signal**: closed-won deal with `dealtype = existingbusiness`
OR distinct expansion pipeline.

**Cross-checks**: subscription auto-renewals should not be counted as
expansion. The bot distinguishes renewal events from true expansion
using line item or property comparison when available.

### Risk

**Primary signal**: customer health score drops below threshold (when
health score reliability check passes), declining product usage (when
usage data is integrated), support ticket spike.

**Secondary signal**: low engagement on previously engaged accounts, key
user departure (when user-count tracking is available), tier downgrade
attempt.

**Cross-checks**: PLG risk signals come primarily from product data.
Without product integration, risk detection is shallow.

### Churn

**Best signal**: subscription cancellation event from billing system, OR
closed-lost deal in dedicated churn pipeline, OR plan tier change to
“Cancelled” or “Churned” value.

**Good signal**: company-level churn property populated.

**Inferred signal**: customer with closed-won deal whose subscription
billing has lapsed (when billing integration provides lapse signal) OR
no activity past subscription term boundary.

**Cross-checks**: free-tier user disappearance is not churn. The bot
only counts churn for paying customers. Free-tier dormancy is tracked
separately.

### Free-tier dormancy and reactivation

**Primary signal for dormancy**: free user with no login or product
activity in 30, 60, 90 days (threshold conditional on product type and
detected free-tier engagement pattern).

**Reactivation signal**: dormant free user returns to product (login
event after dormant period) and ideally converts.

**Cross-checks**: free-tier dormancy is informational; free users are
not paying customers and “losing” them is not churn. However, dormant
free users represent untapped conversion potential, and recirculation
campaigns may be appropriate per the conditional logic of free model.

------------------------------------------------------------------------

## 9. Lifecycle Model

The PLG lifecycle includes states that traditional B2B SaaS lifecycle
does not have (Activated, free-tier states). The traditional MQL and SQL
stages are reinterpreted.

### Canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Visitor | Anonymous traffic, not yet signed up | Not in CRM as contact |
| Subscriber | Marketing-only audience (newsletter, blog, content) | Form submission to non-product asset |
| Lead | Signed up to product, not yet activated | Product signup event, no activation event |
| Activated | Completed first meaningful product action | Activation event fired |
| Engaged | Active product usage | Recurring product engagement signals |
| PQL (sales-assisted) | Product engagement plus firmographic fit indicates sales-readiness | PQL criteria match |
| Customer | Paid conversion | First closed-won deal |
| Power user | High usage, expansion signals | Usage threshold or expansion signal |
| Evangelist | Referral source, advocate, NPS promoter | Referral attribution OR public advocacy OR high NPS |
| Dormant (free-tier) | Free user inactive past threshold | Conditional |
| Churned | Subscription cancelled | Churn signal |

### Mapping client-specific stages

PLG HubSpots vary in lifecycle setup:

- “Customer” applied to free signups: misuse; the bot reports this and
  recommends restricting Customer to paid.
- “MQL” applied to active free users: arguable; in PLG, active free
  users are more analogous to PQL than MQL. The bot maps them to
  Activated or PQL depending on signal strength.
- “SQL” applied to PQL-to-sales handoff: acceptable mapping; sales
  workflow uses SQL semantics.
- “Subscriber” applied to free signups: arguable; some PLG companies
  reserve Subscriber for marketing-only audience and use Lead for free
  signups. Both conventions are workable; the bot reports the convention
  in use.
- Custom states like “Activated”, “PQL”, “Trial”, “Paid Free Trial” are
  common; the bot maps them to canonical states.

### Why traditional lifecycle does not fully fit

Pure PLG has no MQL or SQL in the B2B SaaS sense because there is no
sales handoff in pure self-serve. The funnel is product-driven: Lead
(signed up) goes directly to Activated, then Customer (paid). For
sales-assisted PLG, MQL maps roughly to Activated and SQL maps roughly
to PQL, but the semantics drift from traditional sales-led usage.

The bot reports the client’s lifecycle stage values as informational and
uses event-derived stage as primary. When a misuse pattern is detected
(e.g. all free signups marked Customer), the bot flags it and recommends
configuration that supports correct PLG semantics.

------------------------------------------------------------------------

## 10. Business Model

**Name**: PLG (Product-Led Growth)

**Inclusion rules**: - Product is software with self-serve signup and
free or trial tier - First paid conversion can happen without sales
involvement (even if sales engages later) - Activation in the product is
the central funnel event - Subscription revenue (recurring) for paid
tiers - Bottom-up adoption pattern at minimum for individual / small
team plans

**Exclusion rules**: - No self-serve signup (sales-led only) maps to
SaaS framework - One-time software purchase maps to Transactional
framework (rare) - Two-sided marketplace platform maps to Marketplace
framework - Pure consumer e-commerce maps to E-commerce framework

**Hybrid handling**: most modern PLG companies are sales-assisted PLG
once they reach scale. The bot detects motion type (Section 6) and
applies framework emphasis accordingly. SaaS with PLG side-motion (where
PLG is a marketing tactic for predominantly sales-led business) should
use SaaS framework primarily.

**Revenue trigger**: closed-won deal where `hs_is_closed_won` is true
AND deal represents recurring software subscription. For self-serve
conversions, the deal is typically created by billing integration
immediately upon checkout completion.

------------------------------------------------------------------------

## 11. Funnel and Core Events

### Funnel stages

| Stage | Detection signal |
|:---|:---|
| Visitor | Anonymous traffic (outside CRM) |
| Subscriber | Marketing form signup, no product signup |
| Lead | Product signup event, contact created |
| Activated | Activation event fired |
| Engaged | Recurring product usage signals |
| PQL (sales-assisted only) | PQL criteria match |
| Sales engaged (sales-assisted only) | Sales activity logged or sales pipeline deal created |
| Customer (self-serve paid) | Closed-won deal from billing sync, no sales activity |
| Customer (sales-assisted paid) | Closed-won deal with sales activity history |
| Expansion | New closed-won deal on existing customer OR seat/tier/usage increase |
| Power user | Usage or expansion threshold |
| Dormant free | Free user inactive past threshold |
| Churned | Subscription cancellation |

### Core events

Acquisition: signup or marketing-form contact creation. Activation:
first meaningful product use. PQL (sales-assisted only): qualification
for sales engagement. Conversion: paid plan started. Expansion: revenue
grows on existing customer. Risk: usage drop, support spike, downgrade
signal. Churn: subscription cancelled. Free-tier dormancy: free user
lapses.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| Signup (Lead) | Signup form (when web-based) | – | New Contact with Record Source = INTEGRATION (product) | – | Product platform sync |
| Activation | – | Activation date property populated | – | – | Product event sync |
| PQL | – | PQL flag set OR scoring threshold crossed | – | – | Product engagement plus firmographic match |
| Conversion (Customer) | – | `hs_is_closed_won` = true | New closed-won deal | – | Billing system sync (Stripe/Chargebee/Maxio) |
| Expansion | – | Plan tier property change OR ARR increase | New deal in expansion pipeline | Sales meeting for sales-assisted expansion | Billing event |
| Risk | NPS detractor | Health score drops | Support ticket | Usage drop | Product platform |
| Churn | Cancellation form | Plan tier = Churned, churn date populated | Closed-lost deal in churn pipeline | – | Billing system |
| Free-tier dormancy | – | Days since last login exceeds threshold | – | – | Product platform |

------------------------------------------------------------------------

## 12. KPI Logic

### Acquisition

| KPI | Tier | Formula | Schema Query |
|:---|:---|:---|:---|
| Signup volume | 1 | count of contacts created via product signup | `count(contact) where createdate in [period] and hs_object_source_label matches product integration` |
| Signup by Record Source Detail | 1 | count grouped by detail (channel attribution) | group by `hs_object_source_detail_1` |
| Marketing form contacts (non-signup) | 1 | count of contacts from marketing forms without product signup | filter on `first_conversion_event_name` |
| Cost per signup (when ad spend integrated) | 3 | total ad spend / signup volume | requires ad spend integration |

### Activation (Tier 3 - requires product integration)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| Activation rate | 3 | activated contacts / signup cohort | activation event property populated; cohort by signup date |
| Time to activation (median) | 3 | median of activation date - signup date | same |
| Activation rate by Record Source | 3 | grouped by acquisition channel | same |
| Day-1 / Day-7 / Day-30 retention | 3 | active in window / cohort | requires session tracking |

### Conversion (varies by motion type and free model)

| KPI | Tier | Formula | Schema Query | Conditional |
|:---|:---|:---|:---|:---|
| Free-to-paid conversion rate | 2 | paid customers / signup cohort | numerator: contacts whose first closed-won deal is within X days of signup; denominator: signup cohort | requires free vs paid distinction |
| Trial-to-paid conversion rate (time-bound trial) | 2 | paid within trial expiration / trial cohort | same with trial-period window | conditional on time-bound trial detected |
| Sales-assisted conversion rate (sales-assisted PLG) | 2 | PQLs that closed won / PQL cohort | requires PQL detection | sales-assisted motion |
| Time to first paid conversion (median) | 1 | median of first closed-won closedate - signup date | derived | universal |
| Conversion timing distribution | 1 | percentile distribution of conversion timing | derived; reveals free model conversion patterns | informs free model classification |

### Sales (sales-assisted PLG only)

| KPI | Tier | Formula | Conditional |
|:---|:---|:---|:---|
| PQL volume | 3 | count of contacts meeting PQL criteria | requires PQL definition implemented |
| PQL-to-paid rate | 3 | PQLs that close won / PQL cohort | same |
| Sales-assisted deal volume | 1 | count of closed-won deals with sales activity | universal |
| Sales-assisted ACV | 2 | avg deal amount on sales-assisted deals | requires deal amount consistency |
| Sales-assisted sales cycle | 1 | `deal.days_to_close` for sales-assisted deals | universal |
| PQL-to-sales-engaged rate | 3 | PQLs with sales activity / PQL cohort | requires PQL detection |

### Customer Success and Retention (Tier 3 unless noted)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| GRR | 3 | (starting ARR - churn - contraction) / starting ARR | period-start ARR snapshots plus churn tracking |
| NRR | 3 | (starting ARR - churn - contraction + expansion) / starting ARR | same plus expansion tracking |
| Logo churn (paid customers) | 3 | churned paid customers in period / paid customer count at start | requires churn tracking |
| Revenue churn | 3 | churned ARR in period / starting ARR | requires ARR coverage |
| Expansion rate (per detected model) | 3 | expansion ARR / starting ARR | conditional on detected expansion model |
| Per-seat expansion (when applicable) | 3 | seat count growth across customer base | requires seat count tracking per customer |
| Per-tier expansion (when applicable) | 3 | upgrade transitions across customer base | requires plan tier property |
| Usage-based expansion (when applicable) | 3 | usage growth correlated to ARR growth | requires usage data integration |
| Customer health score distribution | 3 | distribution across health score bands | requires functioning health score |

### Free-tier health (Tier 3)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| Active free user count | 3 | free users with login in last 30 days | requires last login tracking |
| Free DAU/WAU/MAU ratios | 3 | active in narrow window / active in wider window | requires session tracking |
| Free-tier dormancy rate | 3 | dormant free users / total free users | requires last login tracking |
| Reactivation rate | 3 | dormant free users who returned | requires dormancy plus return tracking |

------------------------------------------------------------------------

## 13. Personalization by Motion, Free Model, Expansion Model, and ACV

The bot adjusts recommendations based on detected motion type, free
model, expansion model, ACV band, and retention pattern.

### What the bot looks up per client

**Motion type**: per Section 6.

**Free model**: per Section 7.

**Expansion model**: per Section 7.

**Self-serve ACV**: median deal amount for self-serve closed-won deals
(when distinguishable). Indicates the small / mid / large self-serve
plan economics.

**Sales-assisted ACV**: median deal amount for sales-assisted closed-won
deals. Typically larger.

**Signup volume**: monthly new product signups. Indicates funnel scale.

**Free user base size**: total active free users. Indicates conversion
potential pool.

**Account-level concentration**: top-10 ARR concentration. Useful for
sales-assisted PLG to identify enterprise dependency.

### Motion-specific recommendation emphasis

| Motion | Top diagnostic priorities | Heavy weight templates |
|:---|:---|:---|
| Pure self-serve | Activation rate, free-to-paid conversion, in-product upgrade flow, lifecycle email infrastructure, virality | Lead Generation, Conversion, Onboarding |
| Sales-assisted PLG | Both PLG funnel (signup-to-activation-to-paid) and sales-assisted pipeline (PQL-to-close); PQL definition discipline | Lead Management, Conversion, Account Servicing, Account Growth |
| Hybrid PLG-and-Sales | Full SaaS RevOps with PLG overlay; pipeline coverage, comp design, segmentation | All categories |
| SaaS with PLG side-motion | Apply SaaS framework primarily; use PLG only for trial mechanics | Per SaaS framework |

### Free model and expansion model overlays

These layer on top of motion-specific recommendations to refine
emphasis. The bot generates the appropriate template recommendations per
detected combination.

### ACV band

For sales-assisted deals, ACV bands inform recommendation depth same as
SaaS framework (SMB, Mid-Market, Enterprise). For self-serve deals, ACV
is typically smaller and the relevant band classification is coarser:

| Band | ACV range | Recommendation emphasis |
|:---|:---|:---|
| Self-serve micro | \<\$120 ARR per customer | Volume play; high-volume lifecycle email; minimal CS investment per account |
| Self-serve small | \$120 - \$1.2K ARR | Tier-segmented onboarding; automated CS for lower tiers, light human touch for top |
| Self-serve mid | \$1.2K - \$12K ARR | Account-aware lifecycle; CSM coverage for top tier; expansion focus |
| Sales-assisted | \$12K+ ARR | SaaS framework benchmarks apply for sales-assisted portion |

### Retention pattern

For paid customers, apply SaaS-style retention metrics conditionally.
For free users, apply pattern detection per the Transactional /
E-commerce conditional logic but recognize that free users are not
paying customers and “retention” carries different stakes.

------------------------------------------------------------------------

## 14. Benchmarks

PLG benchmarks vary by motion type, free model, ACV band, and category.
Sources include OpenView’s PLG Index, ProductLed benchmarks, Bessemer
Cloud Index, public S-1 disclosures from PLG companies. Replace with
Blu’s authoritative benchmarks when ingested. Caveats: PLG benchmarks
are noisier than traditional SaaS because the category is younger and
definitions vary.

### Acquisition

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Signup MoM growth | \>10% (early), \>5% (growth) | 5-10% (early), 2-5% (growth) | \<5% (early), \<2% (growth) | Stage-dependent; declining signup is alarm at any stage |
| Cost per signup (when measured) | track trend by channel | – | – | Highly category- and channel-dependent |
| Organic vs paid signup share | \>50% organic | 30-50% | \<30% | Below 30% organic indicates dependence on paid acquisition |

### Activation

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Activation rate | \>50% | 30-50% | \<30% | Highly product-dependent; aspirational targets \>70% for established PLG |
| Time-to-activation (median) | \<24 hours | 1-7 days | \>7 days | Faster activation correlates with higher conversion |
| Day-7 retention (free / activated users) | \>40% | 25-40% | \<25% |  |
| Day-30 retention | \>25% | 15-25% | \<15% |  |

### Conversion

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Free-to-paid conversion (freemium) | \>5% | 2-5% | \<2% | Of free signups, % that convert to paid eventually; varies enormously by category |
| Trial-to-paid conversion (time-bound) | \>25% | 15-25% | \<15% | Of trial users, % that convert at trial end |
| Time to first paid conversion (freemium, median) | \<30 days | 30-90 days | \>90 days | Indicates conversion mechanics |
| Sales-assisted PQL-to-close conversion | \>25% | 15-25% | \<15% | When PQL definition is meaningful |

### Sales-assisted (when motion applies)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Sales-assisted ACV | varies by segment | – | – | Apply SaaS benchmarks per ACV band |
| Sales-assisted sales cycle | 30-90 days | 90-180 days | \>180 days | PQL is pre-qualified, so cycle should be shorter than cold sales |
| PQL volume MoM growth | tracked against signup growth | – | – | PQL growth lagging signup growth indicates conversion or quality issue |

### Retention (paid customers, when measurable)

Apply SaaS framework retention benchmarks: GRR \>90% healthy, NRR \>110%
healthy, etc. Pattern detection per Section 7 should refine free-tier
metric interpretation; paid-tier follows SaaS conventions.

### Expansion (per detected model)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Per-seat expansion: avg seat count growth per account per year | \>30% | 10-30% | \<10% | For team-collaboration PLG |
| Per-tier upgrade rate (annual) | \>15% of customer base | 5-15% | \<5% | Of customers, % upgrading tier per year |
| Usage-based expansion: ARR growth correlation to usage growth | strong correlation | weak correlation | absent | When usage data is integrated |

### Free-tier health (when measurable)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Free DAU/MAU ratio | \>20% | 10-20% | \<10% | Daily active over monthly active; indicates free-user stickiness |
| Free WAU/MAU ratio | \>50% | 30-50% | \<30% |  |
| Free-tier dormancy (90 days) | \<60% | 60-80% | \>80% | Of free users, % inactive past 90 days |

### Maturity stage adjustments

| Stage | ARR range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Early PLG | \<\$1M ARR | Activation, signup volume, conversion mechanics | Loose benchmarks; pattern detection often unreliable due to small cohort |
| Growth PLG | \$1M - \$10M ARR | Conversion optimization, retention infrastructure, sales-assisted motion build (when warranted) | Standard benchmarks emerging |
| Scale PLG | \$10M - \$100M ARR | Full PLG funnel sophistication, expansion engine, sales-assisted scaling, customer success | Standard benchmarks apply; sales-assisted commonly added at this stage |
| Mature PLG | \$100M+ ARR | Multi-product, segmentation, account-based motion overlay, channel diversification, margin discipline | Mature SaaS benchmarks for sales-assisted portion |

------------------------------------------------------------------------

## 15. Required Data Minimum

**Identity**: email plus contact ID. Company domain for B2B PLG.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate`, signup date (when distinct from contact createdate).

**Free vs paid distinction**: clear separation of free users from paying
customers via lifecycle stage, plan tier property, or other reliable
signal. Above 90% accuracy required.

**Revenue value**: `deal.amount` populated on closed-won deals with
consistent magnitude convention.

**Activity / engagement signal**: at least one of
`notes_last_contacted`, `last_activity_date`, `last_engagement_date`
populated.

**Product integration health**: signup events syncing reliably from
product platform; recent sync within last 24 hours; signup count from
product database matches HubSpot contact count within tolerance (5-10%).

**For activation analysis**: activation event property populated for
active users in last 30 days. When absent, activation analysis is
gapped.

**For sales-assisted motion analysis**: clear identification of
sales-assisted deals (via pipeline, owner, or property) and separate
sales-led pipeline structure.

**For confident retention pattern detection**: paid customer cohort age
\>12 months OR more than 200 paid customers.

When any required floor is missed, the bot reports the gap as the
highest-priority finding before analyzing anything else. Product
integration health is reported first because nothing else works without
it.

------------------------------------------------------------------------

## 16. Rules and Edge Cases

### What happens when each event occurs

**Signup**: contact created with Record Source from product integration,
lifecycle workflow may set Lead, signup nurture sequence triggered,
owner not assigned (self-serve) or assigned to BDR (sales-assisted).

**Activation**: activation date populated, lifecycle workflow may
advance to Activated state, in-product onboarding completion email
triggered.

**PQL (sales-assisted)**: PQL flag set, sales handoff workflow
triggered, AE assigned, sales sequence enrolment.

**Paid conversion**: lifecycle workflow sets Customer, plan tier
property updated, customer success workflow triggered, onboarding email
sequence, expansion eligibility evaluation begins.

**Expansion**: deal in expansion pipeline OR plan tier change OR usage
threshold crossed; ARR updated, attribution to triggering signal.

**Risk**: alert to CSM (when account-level CS exists) or automated
re-engagement workflow for self-serve tier.

**Churn**: subscription cancellation logged, lifecycle stage change,
churn reason captured, recirculation eligibility evaluation, free-tier
downgrade if product allows.

**Free-tier dormancy**: free user flagged on dormant list, eligibility
for reactivation campaign per detected free-tier engagement pattern.

### Duplicate handling

- Contacts: dedupe by email primary. For B2B PLG with multiple users at
  same domain, do not auto-merge; treat as related contacts within the
  same account.
- Companies: dedupe by domain primary. For B2B PLG, automatic company
  association by email domain is critical for account-level expansion
  analysis.
- Deals: depending on deal model, apply appropriate proximity rules.
  Subscription rebills should be flagged separately from new
  conversions.

### Missing signals

- No Record Source captured: use Analytics Source as fallback.
- No product integration: activation, free-tier health, and
  product-event metrics are gaps; recommend integration build.
- No deal amount at close: flag for review.
- No PQL definition (sales-assisted PLG): recommend defining PQL based
  on observable signals.
- No activation event tracking: recommend activation event integration.
- Insufficient deal history for retention pattern detection: report
  low-confidence detection.

### Out-of-order events

- Customer status before any deal: lifecycle abuse, not real customer
  status.
- Activation before signup: indicates data loading issue (activation
  event recorded before contact creation in HubSpot).
- Closed-won with future close date: invalid.
- Plan tier set to paid without associated closed-won deal: integration
  gap.
- Free-tier dormancy followed by paid conversion: legitimate
  reactivation event; distinguish from regular new conversion.

### Source conflicts

Same as other frameworks. Record Source primary; Analytics Source
secondary. For PLG, Record Source = INTEGRATION with product platform
identifier is the most common source for product-signup contacts; this
may obscure original marketing source. Recommend integration
configuration that captures original marketing source as a separate
property where possible (typically via UTM capture at signup form
level).

### Bad data handling

When pre-flight reliability checks fail at the alarm level, the bot
reports findings as follows:

1.  Lead with the data quality issue (product integration health gets
    priority for PLG).
2.  Compute Tier 1 metrics (where they remain meaningful without the
    failed check).
3.  Compute Tier 2 metrics with reduced-confidence labels.
4.  Skip Tier 3 metrics that depend on the failing check.
5.  Apply detected motion type, free model, expansion model, and
    retention pattern to interpret metrics conditionally.

Example output structure for a sales-assisted PLG company:

    Account: Example Collaboration App
    Pre-flight findings:
      Product integration health: HEALTHY (Segment sync recent and aligned)
      Free vs paid distinction: HEALTHY (Plan property reliable on 96% of contacts)
      Activation event capture: HEALTHY (firing on 78% of active product users)
      Plan tier reliability: HEALTHY
      Customer status consistency: WATCH (76% of paid contacts at Customer lifecycle)
      Sales motion detection: HEALTHY (clear distinction between self-serve billing
        deals and sales-assisted pipeline deals)
      Sufficient cohort age for retention pattern detection: HEALTHY (28-month paid
        customer cohort, 4,820 paid customers)

    Motion detected:
      Motion type: Sales-assisted PLG
      Confidence: HIGH
      Sales activity share on conversions: 34%
      Sales-assisted deal value share: 67% of bookings
      Implication: split funnel analytics; PLG funnel for self-serve, sales-assisted
        pipeline for enterprise

    Free model detected:
      Model: Freemium with feature limits
      Conversion timing: dispersed (P25 = 14d, P50 = 47d, P75 = 184d)
      Implication: in-product upgrade prompts at feature paywall moments are the
        primary conversion lever

    Expansion model detected:
      Model: Per-seat (primary) plus Per-tier (secondary)
      Avg seat count growth per customer per year: 24%
      Tier upgrade rate (annual): 11%
      Implication: team-invite virality and seat tracking are primary expansion levers;
        secondary tier upgrade motion via feature differentiation

    Retention pattern detected (paid):
      Repeat / NRR pattern applies (subscription-based)
      Apply SaaS framework retention metrics (NRR, GRR, churn)

    Retention pattern detected (free):
      Pattern: Regular repeat (sticky free tier)
      Free DAU/MAU: 24%
      Implication: free-tier engagement is a meaningful conversion runway; reactivation
        campaigns timed to feature limit encounters appropriate

    Top recommendations:
      1. Customer status workflow: 24% of paid contacts not at Customer lifecycle.
         Build workflow that sets lifecycle = Customer when first paid deal closes won.
      2. Self-serve conversion timing optimization: 47-day median conversion timing
         suggests slow value realization. Investigate activation-to-conversion gap;
         consider in-product upgrade prompts at week 2 and week 4 milestones.
      3. Per-seat expansion infrastructure: 24% seat growth indicates strong PLG
         virality; build seat-tracking and account-level CSM engagement for accounts
         above 10 seats.
      4. Sales-assisted PQL definition review: PQL definition is implemented but
         PQL-to-close rate (18%) suggests definition may be too loose. Recommend
         PQL criteria refinement based on top-converting historical patterns.

    Reliable metrics (Tier 1):
      Signup volume: 8,400 last 30 days
      Marketing form contacts (non-signup): 1,240 last 30 days
      Activation rate: 62% (HEALTHY)
      Time-to-activation (median): 8 hours (HEALTHY)
      Free-to-paid conversion: 3.8% (HEALTHY for freemium feature limits model)
      Paid customer count: 4,820
      Sales-assisted deal volume: 84 last quarter
      Sales-assisted ACV: $34K (Mid-market band)
      Sales-assisted sales cycle: 67 days (HEALTHY)

    Conditional metrics:
      NRR (paid customers): 118% (HEALTHY per SaaS benchmarks)
      GRR: 92% (HEALTHY)
      Per-seat expansion (avg seat growth per year): 24% (WATCH band; aspirational >30%)
      Tier upgrade rate (annual): 11% (WATCH band)

    Gap-flagged metrics (Tier 3):
      Day-7 / Day-30 retention curves: cannot compute. Session data not synced.
        Recommend Segment connection or product analytics integration.
      Cohort LTV curves: cannot compute. Requires cohort tracking infrastructure.

    Personalization applied:
      Motion: Sales-assisted PLG
      Free model: Freemium feature limits
      Expansion model: Per-seat primary, Per-tier secondary
      Self-serve ACV: $480 (Self-serve mid band)
      Sales-assisted ACV: $34K (Mid-market band)
      Diagnostic priority: Customer status hygiene, conversion timing optimization,
        per-seat expansion infrastructure, PQL refinement.

------------------------------------------------------------------------

End of PLG framework.
"""
