from ..base import BaseAgent


class MarketplaceAgent(BaseAgent):
    """Marketplace vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered Marketplace framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised Marketplace framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "marketplace"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: Marketplace

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Compute baseline metrics from
validated standard fields. Custom objects, properties, and integrations
are enrichments.

**Marketplaces are two-sided.** Every framework element splits between
supply (sellers, providers, hosts, drivers, freelancers) and demand
(buyers, requesters, riders, guests, clients). The bot must identify
which side a contact represents before applying any other logic. A
unified lifecycle that treats both sides identically will produce
nonsense.

**HubSpot is rarely the source of truth.** The marketplace platform owns
transactions, listings, ratings, matches. HubSpot is typically the BD
layer for supply-side acquisition and the marketing/CRM layer for
demand-side communications. Integration health and side-attribution are
first-class concerns.

**Trust events, not statuses.** The bot derives stage from underlying
events: listing created, first transaction completed, repeat
transaction, account inactivity. Lifecycle stage values from the
client’s HubSpot are validated against event-based truth.

**Record Source over Analytics Source.** `hs_object_source` is set at
creation and not editable in most cases. `hs_analytics_source` became
editable in 2024.

**Detect side, take rate model, liquidity profile, and retention
pattern; do not assume any of them.** Marketplaces vary enormously: some
are commission-only, some charge listing fees, some are
subscription-based for one side, some have take rates from both sides.
Some have instant matching, some are pull-based searches, some are
time-bound auctions. The bot observes the actual model and applies
recommendations conditionally.

**Liquidity is the central marketplace health metric, but only
computable when both sides are tracked.** When the client’s HubSpot only
has one side reliably (typically demand, with supply living in the
platform), the bot reports liquidity-related metrics as gaps and
recommends supply-side tracking infrastructure.

**Validate before trusting.** Pre-flight reliability checks gate every
metric.

------------------------------------------------------------------------

## 1. Category Definition

Marketplace businesses operate two-sided platforms that connect supply
(people offering goods, services, or capacity) with demand (people
seeking them) and capture revenue through transaction fees, listing
fees, subscription fees, or hybrid models. Includes B2C marketplaces
(Airbnb, DoorDash, Etsy), B2B marketplaces (Faire, Reverb, 1stdibs),
service marketplaces (Upwork, Fiverr, TaskRabbit), peer-to-peer
platforms, and vertical specialty marketplaces.

Distinct from E-commerce because the platform does not own inventory or
fulfill directly; supply is independent. Distinct from SaaS because the
product is the connection between sides, not software functionality
directly. Distinct from Transactional because the seller relationship is
ongoing rather than a single transaction. Distinct from Services because
the platform is not delivering the service itself; it is enabling third
parties to deliver.

Hybrid cases are common: a marketplace that takes some inventory
positions becomes part E-commerce; a marketplace that charges
supply-side subscription becomes part SaaS for that side; a marketplace
that operates a managed service tier becomes part Services.

## 2. Common GTM Motion

Marketplaces typically need to cold-start one side before the other can
scale, and the harder side varies by marketplace. Many marketplaces
invest first in supply (BD-led, sales reps recruiting providers, often
with concierge onboarding) so demand has something to consume.

Demand-side acquisition is typically marketing-led: paid acquisition,
content, SEO, referrals, partnerships. Demand-side onboarding is usually
self-serve.

Supply-side acquisition often involves outbound sales, BD reps, or
partner programs. Onboarding can be high-touch (manual review, listing
assistance, photoshoot, training) or self-serve depending on the
marketplace.

Both sides have separate retention motions. Supply-side retention
focuses on listing utilization, fill rates, earnings, supply-side
product features. Demand-side retention focuses on repeat transactions,
recommendation quality, trust signals.

Trust and safety infrastructure (reviews, ratings, dispute resolution,
identity verification) is foundational and cross-side. Reputation
systems amplify network effects but introduce data integrity concerns.

## 3. KPIs by Function

### Supply-side acquisition and growth

New supply contacts, supply onboarding completion rate,
time-to-first-listing, listing volume created, active supplier rate,
supplier churn, supplier earnings (when tracked), supplier NPS.

### Demand-side acquisition and growth

New demand contacts, demand-side conversion rate
(signup-to-first-transaction), repeat purchase rate, customer lifetime
value, demand-side churn or dormancy.

### Liquidity (cross-side; requires both sides tracked)

Total transactions, time-to-match, fill rate (% of demand requests that
find supply), search-to-transaction rate, supply utilization (% of
supply with at least one transaction in period), match quality.

### Marketplace economics

Gross Merchandise Value (GMV), take rate (revenue / GMV), revenue,
transaction volume, average transaction value, transaction value
distribution.

### Trust and safety

Review submission rate, rating distribution, dispute rate, dispute
resolution time, fraud signal volume, account verification rate.

The KPIs split by side throughout the framework. The bot does not
collapse them.

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
`hs_object_source_detail_2`, `hs_object_source_detail_3`. For
marketplaces, Record Source values often come from platform integrations
and may use detail fields to indicate side (Supplier Signup form vs
Customer Signup form). The bot extracts side hints from detail field
pattern matching during onboarding analysis.

**Analytics Source (secondary)**: `hs_analytics_source` and related
fields.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`. First conversion type often reveals
side: a “Become a Provider” form versus a “Browse Listings” interaction.

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open`, `hs_email_click`,
`hs_sales_email_last_opened`, `hs_sales_email_last_clicked`,
`hs_sales_email_last_replied`, `hs_email_sends_since_last_engagement`.

**Deal association**: `num_associated_deals`. Behaviour varies
enormously across marketplace HubSpots: some create a deal per
transaction (works for low-volume B2B marketplaces, breaks for
high-volume B2C), some create deals only for supply-side BD (recruiting
suppliers), some don’t use deals at all.

### Company (when present)

`createdate`, `hubspot_owner_id`, `num_associated_contacts`,
`num_associated_deals`, `recent_deal_amount`, `recent_deal_close_date`,
`total_revenue`, `last_activity_date`, `lifecyclestage`, `industry`,
`hs_object_source`, `hs_object_source_label`.

For B2B marketplaces, suppliers and buyers are often companies. For B2C
marketplaces, contacts are typically individuals; companies may not be
used.

### Deal (always present, but used inconsistently across marketplace HubSpots)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype`, `hubspot_owner_id`, `num_associated_contacts`.

**Close state**: `hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`, `hs_closed_won_date`, `closed_lost_reason`,
`days_to_close`.

**Stage history**: `hs_date_entered_<stageId>`, `hs_v2_*` versions.

In marketplace HubSpots, the meaning of a deal varies: - BD deals for
supplier acquisition (sales-led recruiting; deal closes won when
supplier signs up) - Transaction deals (one deal per platform
transaction, synced from the marketplace platform) - Account deals (one
deal per supplier or buyer relationship lifecycle)

The bot identifies which model the client uses during onboarding
analysis.

### Activity

Standard schema. Calls and meetings are common for B2B marketplace BD on
supply side. Demand-side activity is typically email and SMS only.

### Custom marketplace objects (typical when present)

Mature marketplace HubSpots often build custom objects: - Provider /
Supplier object (separate from contact for B2C marketplaces where the
supplier may not be a contact) - Listing object (with status, price,
performance) - Transaction object (when high volume makes
deal-per-transaction impractical) - Match object (for liquidity
tracking)

When these exist, the bot leverages them. When absent, the bot falls
back to deal-based proxies and flags the infrastructure gap.

### What the bot derives from standard schema

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source | `contact.hs_object_source_label` and detail fields |
| Side hint (supply vs demand) | `contact.first_conversion_event_name` plus Record Source Detail patterns plus form ID matching |
| Engagement recency | `last_engagement_date`, `last_activity_date`, email engagement dates |
| Transaction count (when deals = transactions) | `contact.num_associated_deals` |
| GMV proxy (when deals = transactions) | sum of `deal.amount` for closed-won deals |
| Active vs dormant (per side) | days since last engagement or last transaction, threshold conditional on detected pattern |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: marketplace HubSpots have specific failure
patterns rooted in two-sided complexity.

### Properties to treat as unreliable by default

**Lifecycle stage.** Editable, frequently misused. Marketplace-specific
failure: a unified lifecycle is applied to both sides (e.g. a “Customer”
lifecycle for both suppliers who signed up and buyers who transacted),
making side-segmented analysis impossible without additional fields.

**Analytics source.** Editable since 2024.

**Deal amount.** When deals represent platform transactions, amount may
represent GMV (gross transaction value) or take (marketplace revenue)
inconsistently. The bot validates magnitude and flags mixed conventions.
When amount represents GMV, the bot computes take separately when take
rate is known.

**Side identification.** Often missing entirely. Many marketplace
HubSpots have no field that distinguishes a supplier from a buyer,
requiring inference from form names, Record Source Detail, or
association patterns.

`dealtype` rarely captured.

### Properties to trust by default

Record Source, object timestamps, boolean state flags, engagement
recency, integration property updates from healthy syncs.

### Pre-flight reliability checks

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Side identification coverage | % of contacts with reliable side attribution (custom property, distinct list, or inferable from Record Source) | \>85% | 50-85% | \<50% | All side-segmented metrics; without this, marketplace analysis collapses |
| Integration health | last sync time of marketplace platform integration; consistency of platform vs HubSpot counts | recent and aligned | sync delayed \>24h | broken or diverging | All transaction-level metrics |
| Both sides tracked | both supply and demand side contacts present in HubSpot with reliable identification | yes | one side strong, other weak | only one side present | Liquidity metrics, cross-side analysis |
| Deal model clarity | clear understanding of what a deal represents (BD, transaction, account) and consistent application | yes | mixed model | unclear / mixed | Bookings, GMV, transaction count |
| Customer status consistency | % of contacts (or companies) with closed-won deals tagged as Customer at appropriate level | \>85% | 60-85% | \<60% | Customer count, retention metrics per side |
| Deal amount consistency | variance and pattern of `deal.amount` magnitude | manageable | suspect mixing | mixed (GMV vs take) | GMV, revenue, AOV |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source-level analysis |
| Active ownership (where applicable) | % of records with `hubspot_owner_id` matching active user | \>95% | 85-95% | \<85% | Owner-level reporting (mostly relevant for supply-side BD) |
| Sufficient cohort age for retention pattern detection (per side) | each side’s customer cohort age \>12 months OR more than 200 active customers per side | yes | partial | absent | Retention pattern detection per side |

### Confidence tiers for marketplace metrics

**Tier 1 (high confidence, computable from validated standard schema
after side identification)**: - Contact volume by side and Record
Source - Activity volume per side - BD deal volume (when supplier
acquisition uses deals) - Engagement metrics per side - Side-segmented
dormancy

**Tier 2 (medium confidence, requires reliability check pass)**: - GMV
(when deals reliably represent transactions and amount represents
transaction value) - Take or revenue (when take rate is known and
consistent) - Average transaction value - Repeat transaction rate (per
side) - Source-level conversion per side

**Tier 3 (requires custom infrastructure or platform integration
depth)**: - Liquidity metrics (time-to-match, fill rate,
search-to-transaction rate) - Supply utilization - Match quality -
Per-listing performance - Cross-side cohort analysis - Dispute and trust
metrics - Predictive supplier or buyer churn

------------------------------------------------------------------------

## 6. Side Detection

Before any other logic, the bot identifies whether each contact is on
the supply side, demand side, both, or neither. Without this,
marketplace analytics is meaningless.

### Detection signals (in priority order)

**Best signal**: explicit Side custom property (e.g. “User Type” with
values Supplier / Buyer / Both, or distinct boolean flags per side).
When present and populated above 85%, this is canonical.

**Good signal**: distinct lifecycle stage values per side (custom
Lifecycle Pipeline configuration, sometimes seen in mature marketplaces
using HubSpot Marketing Hub Enterprise).

**Strong inference signal**: Record Source Detail or form ID indicates
side (e.g. “Become a Provider” form maps to supply, “Sign Up to Browse”
maps to demand). Pattern matching on form names and conversion event
names typically identifies 60-80% of contacts when implemented.

**Weak inference signal**: association patterns (e.g. contact associated
to a deal in the BD pipeline implies supply side; contact with high
transaction count and no BD activity implies demand). Used as last
resort.

**No signal**: contact created via IMPORT or MANUAL with no other
identifiers. Flagged as “Unknown side” and reported as a data quality
issue.

### What the bot does when side identification fails

When side identification coverage is below the alarm threshold (\<50%),
the bot:

1.  Reports the gap as the highest-priority data quality issue.
2.  Recommends adding a Side custom property with workflow population
    from Record Source Detail and form ID patterns.
3.  Computes only side-agnostic metrics (total acquisition volume, total
    deal volume) until the gap is fixed.
4.  Skips all side-segmented analysis until coverage clears the watch
    threshold.

### Cross-side contacts

Some marketplaces allow the same person to be both supplier and buyer
(e.g. peer-to-peer platforms where users sell and buy on the same site).
When detected, the bot tags these contacts as Both and reports
cross-side metrics separately.

------------------------------------------------------------------------

## 7. Retention Pattern Detection per Side

The bot detects retention pattern separately for supply and demand. The
patterns may differ: a marketplace may have high-repeat demand (frequent
buyers) and one-and-done supply (occasional sellers), or vice versa.

### Inputs the bot computes (per side)

For each side independently: - Repeat transaction rate (% of side
participants with more than one transaction) - Average per-participant
transaction count - Time between transactions distribution (median, P25,
P75) - Customer cohort age and count - Active rate (% of side
participants active in last 30/90 days)

### Pattern classification per side

Same four-pattern model as Transactional and E-commerce, applied
separately to each side:

- One-and-done (most common on supply side for “casual seller”
  marketplaces; uncommon on demand side except for premium
  high-consideration categories)
- Occasional repeat
- Regular repeat
- High repeat (most common on demand side for frequent-use marketplaces;
  common on supply side for professional sellers)

### Cross-pattern combinations

The combination of patterns across sides drives recommendations:

| Supply pattern | Demand pattern | Marketplace archetype | Diagnostic emphasis |
|:---|:---|:---|:---|
| High repeat | High repeat | Frequent-use both-sides marketplace (food delivery, ride-share) | Liquidity, match quality, both-side retention |
| High repeat | One-and-done / Occasional | Professional supply, casual demand (home services, freelance) | Supply-side retention is primary; demand acquisition continuous |
| One-and-done / Occasional | High repeat | Casual supply, professional demand (consignment to professional buyers, niche marketplaces) | Demand-side retention is primary; supply acquisition continuous |
| One-and-done / Occasional | One-and-done / Occasional | Long-cycle marketplace (wedding services, real estate, premium goods) | Acquisition focus on both sides; trust and reviews critical |

### How detected patterns shift framework application

For each side, retention emphasis follows the same conditional logic as
Transactional and E-commerce frameworks. The bot generates
recommendations specific to each side based on its detected pattern.

------------------------------------------------------------------------

## 8. Multi-Signal Event Detection

### Side-segregated lifecycles

The bot maintains parallel event detection for supply and demand. Below,
each event is described with side-specific detection.

### Acquisition (per side)

**Primary signal**: contact created with `hs_object_source_label`
indicating side-specific entry. Pattern matching on Record Source Detail
for “supplier”, “provider”, “host”, “seller”, “driver”, “freelancer”
pattern words for supply; “buyer”, “customer”, “browse”, “search”
pattern words for demand.

**Secondary signal**: `first_conversion_event_name` matches
side-specific signup form.

**Cross-checks**: contacts created via IMPORT or BULK_API often
represent platform user backfills; segregate from organic acquisition
cohort.

### Activation - Supply side

**Primary signal**: first listing created (when listing object exists)
OR custom property indicating supplier onboarded OR first BD deal
closed-won (for sales-led supplier acquisition).

**Secondary signal**: meeting held with `hs_meeting_outcome` = COMPLETED
for BD-led supply onboarding.

**Cross-checks**: a supplier signed up but never created a listing is a
supply onboarding gap. The bot reports time-to-first-listing and flags
suppliers stuck in pre-activation state.

### Activation - Demand side

**Primary signal**: first transaction completed OR account verification
completed (when verification is required pre-purchase).

**Secondary signal**: first session activity, first product view (when
behavioural data is synced).

**Cross-checks**: signed-up demand-side contacts who never transact are
typical and not necessarily a problem; the bot tracks the conversion
rate and time-to-first-transaction without flagging individual contacts.

### Conversion - Supply side

For supply, “conversion” means earning revenue on the platform.
Detection:

**Primary signal**: supplier has at least one transaction completed
where they were the supply party.

**Secondary signal**: integration property indicating transactions
completed \> 0.

### Conversion - Demand side

**Primary signal**: contact has at least one transaction completed where
they were the demand party (deal closed-won when deals = transactions,
OR custom property indicating purchase).

### Repeat transaction (per side)

**Primary signal**: side participant has more than one transaction,
after excluding subscription rebills, recurring auto-renewals, or
sub-transactions of a single order.

**Cross-checks**: frequency of repeat varies enormously; the bot
interprets per detected pattern for the side.

### Risk - Supply side

**Primary signal**: supplier with declining listing utilization,
dropping fill rate, no new listings in extended period, low ratings,
dispute spike.

**Secondary signal**: supplier expressing churn intent (cancellation
request, support ticket about platform issues).

**Cross-checks**: supply-side risk requires platform integration depth
to detect well.

### Risk - Demand side

**Primary signal**: demand-side participant with declining transaction
frequency, low ratings given, dispute initiation, support ticket spike.

### Dormancy (per side, conditional on detected pattern)

For each side, the bot computes days-since-last-activity. Interpretation
conditional on detected pattern for that side:

- One-and-done detected for that side: dormancy is the default.
- Occasional / regular / high repeat: dormancy beyond pattern threshold
  is risk or recirculation candidate.

### Liquidity events (cross-side)

When both sides are tracked and transactions are visible:

**Match event**: a transaction occurs (a supply-side participant
transacts with a demand-side participant). The bot tracks match
frequency, time-to-match for given listings or requests, and
supply-demand balance.

**Failed match**: a demand-side request that does not find supply within
a window, OR a supply-side listing that does not find demand within a
window. Detection requires platform integration to surface unmet demand
or unsold supply, which most HubSpots do not have natively.

When liquidity event tracking is absent, the bot reports liquidity
metrics as Tier 3 gaps and recommends platform integration extensions.

------------------------------------------------------------------------

## 9. Lifecycle Model

The marketplace lifecycle is dual: parallel lifecycles for supply and
demand. The bot maintains both and reports them separately.

### Supply-side canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | Marketing-only audience interested in becoming a supplier | Form signup for supplier content, no application yet |
| Lead | Application or interest signal | Supplier application submitted, BD outbound positive response |
| Onboarding | Application accepted, in setup | Manual stage progression, BD deal in onboarding stage, custom onboarding status property |
| Listed | First listing live | First listing object created, integration property update |
| Active | Transacting regularly | Recent transactions per detected pattern threshold |
| Top performer | High earnings, high listing performance | Custom tier property when tracked OR top-quartile transaction volume |
| Dormant | No recent listing activity or transactions | Conditional on detected supply-side pattern |

### Demand-side canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | List signup, no transaction yet | Form signup for demand-side content |
| Lead | Account created, browsing | Account creation with verification, browsing activity |
| Browser | Active engagement, no transaction | Listing views, search activity (when synced) |
| First-time customer | First transaction completed | First closed-won deal where contact is demand-side |
| Repeat customer | Subsequent transaction | Second or later transaction |
| Power user | High transaction frequency | Top-quartile transaction count or value |
| Lapsed (conditional) | No transaction past pattern-appropriate threshold | Conditional on detected demand-side pattern |

The MQL and SQL stages from B2B sales-led lifecycle do not apply to
marketplace demand side. They may apply to supply side when supplier
acquisition is sales-led (BD reps recruiting suppliers); in that case,
supply-side MQL = supplier showed qualifying interest, SQL = supplier
deal created in BD pipeline.

### When lifecycle stage is mismanaged

Marketplace HubSpots commonly misapply lifecycle stage in these ways,
all of which the bot flags:

- Same lifecycle stage applied to both sides without distinction
- “Customer” lifecycle applied to suppliers (suppliers earn rather than
  buy from the platform; “Customer” semantically reflects demand)
- “Subscriber” lifecycle applied to platform users in general
  (overloading the marketing-list semantic)
- Sales-led lifecycle imported from a CRM template designed for B2B SaaS

The bot reports these patterns and recommends configuration that
supports parallel side-specific lifecycles.

------------------------------------------------------------------------

## 10. Business Model

**Name**: Marketplace

**Inclusion rules**: - Two-sided platform connecting independent supply
with demand - Revenue derived from transaction fees, listing fees,
subscription, or hybrid - Platform does not own inventory directly (some
marketplaces do hold partial inventory; treat as hybrid) - Both sides
exist as distinct user types with separate experiences

**Exclusion rules**: - Single-sided commerce maps to E-commerce
framework - B2B with consultative sales motion maps to Transactional or
Services framework - SaaS with affiliate / referral revenue maps to SaaS
framework - Pure aggregator with no transactions (lead generation only)
maps to Transactional or Services framework

**Hybrid handling**: - Platform holding partial inventory: inherit
E-commerce framework for owned-inventory portion - Subscription tier for
one or both sides: inherit SaaS framework for subscription portion -
Managed service tier: inherit Services framework for managed portion

**Revenue trigger**: transaction completed on the platform AND
marketplace fee or take captured. Detection method varies based on
whether deals represent transactions and whether amount represents GMV
or take.

------------------------------------------------------------------------

## 11. Funnel and Core Events

### Funnel stages (per side)

| Side | Stage | Detection signal |
|:---|:---|:---|
| Supply | Application | Supplier signup form submission |
| Supply | Onboarding | Application accepted, in setup |
| Supply | First listing | Listing object created |
| Supply | First transaction | Supplier completed first transaction as supply |
| Supply | Active | Transacting regularly per detected pattern |
| Supply | Dormant (conditional) | Inactivity past pattern threshold |
| Demand | Signup | Account created |
| Demand | Browsing | Active session activity, listing views |
| Demand | First transaction | First closed-won as demand party |
| Demand | Repeat | Subsequent transaction |
| Demand | Lapsed (conditional) | Inactivity past pattern threshold |
| Cross-side | Match | Transaction occurs |
| Cross-side | Failed match | Demand request unmet OR listing unsold within window |

### Core events

Acquisition (per side): new contact identified as side participant.
Activation (per side): supply side - first listing; demand side - first
transaction. Repeat transaction (per side): subsequent transaction.
Match: cross-side liquidity event. Risk (per side): churn signals
specific to the side. Dormancy (per side): lapse beyond pattern
threshold.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| Supply acquisition | Supplier signup form | Side property = Supplier | New Contact with Record Source matching supply pattern | BD outbound logged | Platform sync of supplier registration |
| Supply onboarding | – | Onboarding status property change | – | Onboarding meeting held | Platform sync of supplier verification |
| Supply first listing | – | First listing date property | New Listing custom object | – | Platform sync of listing creation |
| Supply first transaction | – | First transaction date | Closed-won deal with supplier as supply party (when deals = transactions) | – | Platform sync of completed transaction |
| Demand acquisition | Demand-side signup form | Side property = Buyer | New Contact with Record Source matching demand pattern | – | Platform sync of buyer registration |
| Demand first transaction | – | First transaction date | Closed-won deal with contact as demand party | – | Platform sync of completed transaction |
| Repeat transaction (per side) | – | – | New closed-won deal on existing side participant | – | Platform sync |
| Match | – | Transaction status = Completed | Transaction custom object | – | Platform sync |
| Risk (per side) | NPS detractor | Custom risk flag, dispute count | Support ticket | Cancellation activity | Platform integration risk signal |
| Dormancy (per side) | – | Days since last activity exceeds pattern threshold | – | – | – |

------------------------------------------------------------------------

## 12. KPI Logic

### Acquisition (per side)

| KPI | Tier | Formula | Conditional |
|:---|:---|:---|:---|
| Supply contact volume | 1 | count of supply-identified contacts created in period | requires side identification check pass |
| Demand contact volume | 1 | count of demand-identified contacts created in period | requires side identification check pass |
| Supply by Record Source | 1 | grouped by Record Source Label and Detail | requires side identification plus Record Source coverage |
| Demand by Record Source | 1 | grouped by Record Source Label and Detail | same |

### Supply-side activation and growth

| KPI | Tier | Formula | Schema Query / Requirement |
|:---|:---|:---|:---|
| Time-to-first-listing | 1 or 3 | days from supply acquisition to first listing creation | Tier 1 if listing object exists; Tier 3 if relying on integration property |
| Active supplier rate | 2 | suppliers with at least one transaction in trailing 30/90 days / total suppliers | requires transaction tracking |
| Supplier churn | 2 or 3 | suppliers active in prior period not active in current period | conditional on detected supply retention pattern |
| Listing volume | 3 | count of listings created in period | requires Listing object or integration property |
| Supplier earnings (avg) | 3 | avg of cumulative supplier earnings across active suppliers | requires earnings property from platform integration |

### Demand-side conversion and growth

| KPI | Tier | Formula | Schema Query / Requirement |
|:---|:---|:---|:---|
| Demand signup-to-transaction conversion | 1 | demand-side contacts with first transaction within 90 days of signup / demand cohort | requires side identification |
| Demand repeat purchase rate | 2 | demand contacts with more than one transaction / total demand customers | requires customer status check pass per side |
| Demand LTV | 1 | sum of `deal.amount` per contact (deal-as-transaction model) | when deals reliably represent transactions |
| Time between purchases (demand side) | 2 | distribution of gaps between consecutive transactions per demand contact | per detected pattern |

### Marketplace economics

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| GMV | 2 | sum of transaction value across closed-won deals (when deals = transactions and amount = GMV) | deal model clarity check pass |
| Take rate | 3 | revenue / GMV | requires take rate known or revenue separately tracked |
| Revenue | 2 or 3 | take rate \* GMV when consistent, OR sum of marketplace-take property when tracked | conditional |
| Average transaction value | 2 | avg of transaction value | requires consistent amount convention |
| Transaction volume | 2 | count of completed transactions | when deals = transactions |
| Transaction value distribution | 2 | percentile distribution | same |

### Liquidity (Tier 3 unless integration depth)

| KPI | Tier | Formula | Requirement |
|:---|:---|:---|:---|
| Time-to-match | 3 | avg time from request creation to match | platform integration with match events |
| Fill rate | 3 | matched requests / total requests | platform integration with unmet demand visibility |
| Search-to-transaction rate | 3 | searches that lead to transactions / total searches | platform integration with search events |
| Supply utilization | 3 | suppliers with at least one transaction in period / total active suppliers | requires both sides tracked |
| Match quality (rating average) | 3 | avg rating on completed transactions | rating integration |
| Cross-side cohort liquidity | 3 | cohort matrix of supply availability vs demand requests | full integration depth |

### Trust and Safety (Tier 3)

| KPI                       | Tier | Requirement                         |
|:--------------------------|:-----|:------------------------------------|
| Review submission rate    | 3    | review system integration           |
| Rating distribution       | 3    | rating data integration             |
| Dispute rate              | 3    | dispute / refund ticket integration |
| Account verification rate | 3    | verification status integration     |

------------------------------------------------------------------------

## 13. Personalization by Liquidity Profile and Take Rate

The bot adjusts recommendations based on the marketplace’s liquidity
profile, take rate model, side asymmetry, and detected retention
patterns per side.

### What the bot looks up per client

**Supply-to-demand ratio**: count of active supply contacts vs count of
active demand contacts. Indicates which side is the bottleneck.

**Take rate model**: commission only, listing fee, subscription on one
or both sides, hybrid. Detected from pricing structure (often via
integration data) and confirmed during onboarding analysis.

**Liquidity profile**: how matches happen. Instant match (immediate
algorithmic pairing), pull-based (demand searches and selects supply),
push-based (supply pushes to demand), time-bound (auctions, time-limited
offers). Inferred from platform behaviour and integration data.

**Per-side retention patterns**: independently detected per Section 7.

**GMV concentration**: % of GMV from top suppliers and top buyers. High
concentration on either side is a network risk.

### Marketplace stage classification

| Stage | Indicators | Diagnostic priority |
|:---|:---|:---|
| Cold start | One side under 100 active participants, weekly transaction volume \<100 | Solving the bootstrap problem; concierge supply or demand acquisition |
| Single-side dominant | Strong side has 10x more participants than weak side | Acquiring weak side; balancing the marketplace |
| Liquidity building | Both sides growing but match rates and time-to-match still problematic | Improving match algorithms, reducing friction, supply-demand balance |
| Liquidity established | Reliable match rates, strong network effects forming | Retention and frequency growth on both sides; trust and safety scaling |
| Mature | Strong both-side retention, high frequency, low concentration | Optimization, expansion (categories, geographies), defensibility |

### Recommendation emphasis by marketplace stage

| Stage | Supply-side emphasis | Demand-side emphasis | Cross-side / liquidity emphasis |
|:---|:---|:---|:---|
| Cold start | Concierge supply acquisition, BD-heavy, manual onboarding, high-touch supplier success | Limited demand investment until supply liquidity exists; build waitlist | Manual matching, founder involvement |
| Single-side dominant | Continue strong-side retention; do not over-invest acquisition that worsens imbalance | Heavy acquisition investment on weak side; subsidize early demand if supply-strong | Match facilitation, address bottlenecks |
| Liquidity building | Supplier retention infrastructure, listing performance optimization, supplier-side product development | Demand acquisition diversification, demand-side retention motion | Liquidity metrics infrastructure, match quality measurement |
| Liquidity established | Supply tier programs, top-supplier success, supplier product expansion | Loyalty programs (per detected pattern), referral programs, premium tiers | Trust and safety scaling, dispute reduction, verification |
| Mature | Supply efficiency, churn reduction at scale | Retention sophistication, expansion into adjacent categories | Network effect defensibility, geographic expansion, vertical expansion |

### Conditional retention emphasis (per side)

Same pattern-specific logic as Transactional and E-commerce, applied
separately to each side per detected pattern. Recommendations to make
and not make follow the same rules. The two sides may receive completely
different retention motion recommendations.

### Take rate model overlay

- **Commission only**: marketplace economics depend on transaction
  volume and value. Recommendations focus on transaction frequency and
  AOV.
- **Listing or subscription on supply side**: supplier retention is
  doubly important because subscription revenue compounds with
  transaction take. Apply SaaS-style retention metrics for the
  subscription portion.
- **Subscription on demand side**: demand retention is similarly
  compounded; apply SaaS retention for the subscription portion.
- **Hybrid take models**: the bot computes economics per stream and
  reports separately.

------------------------------------------------------------------------

## 14. Benchmarks

Marketplace benchmarks vary enormously by category, stage, and take rate
model. Sources include Andreessen Horowitz marketplace benchmarks, NFX
research, platform-specific reports. Replace with Blu’s authoritative
benchmarks when ingested. Caveats: marketplace stage and category drive
most variance; some benchmarks make sense only at certain stages.

### Acquisition (per side)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Supply application-to-onboarding completion | \>60% | 40-60% | \<40% | When onboarding is high-touch |
| Supply application-to-onboarding (self-serve) | \>75% | 50-75% | \<50% |  |
| Time-to-first-listing | \<7d | 7-30d | \>30d |  |
| Demand signup-to-first-transaction conversion (90d) | \>25% | 15-25% | \<15% | Highly category-dependent |
| Demand signup-to-first-transaction (180d) | \>40% | 25-40% | \<25% |  |
| Time-to-first-transaction (median) | \<14d | 14-60d | \>60d | Faster cycle for impulse categories |

### Marketplace economics

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| GMV growth (MoM) | \>10% | 5-10% | \<5% | Stage-dependent; faster early, slower at scale |
| Take rate | varies by category | – | – | Track trend; declining take rate may indicate competitive pressure |
| Average transaction value | track trend | – | – |  |
| GMV concentration top-10 suppliers | \<20% | 20-40% | \>40% | High concentration is network risk |
| GMV concentration top-10 buyers | \<15% | 15-30% | \>30% | Same |

### Liquidity (when measurable)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Time-to-match (median) | category-specific | – | – | Same-day for ride-share; longer for niche |
| Fill rate | \>90% | 75-90% | \<75% | Of demand requests, % that find supply |
| Search-to-transaction rate | \>5% | 2-5% | \<2% | Of searches, % that lead to transaction |
| Supply utilization | \>50% | 30-50% | \<30% | Of active suppliers, % with transactions in period |

### Retention (conditional per detected pattern, per side)

Apply pattern-specific thresholds per Transactional / E-commerce
framework. Repeat transaction rate alarm thresholds only apply when the
side’s detected pattern is occasional repeat or stronger.

### Trust and Safety (when measurable)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|----|
| Dispute rate | \<2% of transactions | 2-5% | \>5% |  |
| Dispute resolution time (median) | \<72h | 72h - 7d | \>7d |  |
| Review submission rate | \>25% of transactions | 10-25% | \<10% |  |
| Negative review rate (1-2 stars) | \<10% of reviews | 10-20% | \>20% |  |
| Account verification rate | \>80% of supply, varies for demand | 60-80% | \<60% |  |

### Maturity stage adjustments

| Stage | GMV range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Cold start | \<\$1M GMV | Cold start solution, manual matching, single-side concentration on the harder side | Loose benchmarks; metrics often unmeaningful at this scale |
| Bootstrapping | \$1M - \$10M GMV | Liquidity development, supply-demand balance, basic retention infrastructure | Standard benchmarks emerging |
| Growth | \$10M - \$100M GMV | Both-side retention, liquidity optimization, geographic or category expansion | Standard benchmarks apply |
| Scale | \$100M+ GMV | Network effect defensibility, trust scaling, top-tier supplier and customer programs, multi-region complexity | Mature marketplace benchmarks |

------------------------------------------------------------------------

## 15. Required Data Minimum

**Identity**: email plus contact ID. Companies for B2B marketplaces.

**Side identification**: at least 50% of contacts must have reliable
side attribution (via custom property, distinct lifecycle,
distinguishable Record Source Detail, or inferable form/conversion
patterns). Below this threshold, marketplace analysis cannot proceed.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate` (when deals = transactions or BD), transaction timestamps
from platform integration.

**Revenue value**: `deal.amount` populated with consistent magnitude
convention. The bot must be able to determine whether amount represents
GMV or take.

**Activity / engagement signal**: at least one of
`notes_last_contacted`, `last_activity_date`, `last_engagement_date`
populated.

**Owner (where applicable)**: `hubspot_owner_id` populated for
supply-side BD records.

**Both sides tracked**: when liquidity analysis is required, both supply
and demand contacts must be present and identifiable in HubSpot. When
only one side is tracked (the other lives only in the platform), the bot
reports liquidity metrics as gaps.

**For confident retention pattern detection per side**: each side’s
customer cohort age \>12 months OR more than 200 active participants per
side.

When any required floor is missed, the bot reports the gap as the
highest-priority finding before analyzing anything else. Side
identification coverage is reported first because nothing else is
meaningful without it.

------------------------------------------------------------------------

## 16. Rules and Edge Cases

### What happens when each event occurs

**Supply acquisition**: Record Source captured automatically, side
property populated via workflow, BD owner assigned (when sales-led),
supplier nurture or onboarding sequence triggered.

**Supply activation (first listing)**: integration sync updates listing
count and first listing date, supplier success outreach triggered,
milestone email sent.

**Demand acquisition**: side property populated, demand-side welcome
flow, no immediate purchase required.

**Demand activation (first transaction)**: customer status updated,
post-transaction NPS request, repeat-purchase nurture flow per detected
pattern.

**Repeat transaction (per side)**: cumulative metrics updated, loyalty
or tier programs evaluated.

**Match (cross-side)**: liquidity metrics updated, match quality
tracked.

**Risk (per side)**: side-specific intervention; supply-side risk routes
to supplier success, demand-side risk routes to customer support.

**Dormancy (per side, conditional)**: action depends on detected pattern
for the side.

### Duplicate handling

- Contacts: dedupe by email. For B2B marketplaces, secondary by company
  domain. For peer-to-peer marketplaces, watch for
  same-person-both-sides cases that may appear as separate contacts; if
  identifiable, link as Both side.
- Companies: standard dedupe.
- Deals: depending on deal model (BD, transaction, account), apply
  appropriate proximity rules. Same-cart splits in transaction-deal
  models should be merged.

### Missing signals

- No side identification: priority-zero gap; no marketplace analysis
  until fixed.
- No Record Source captured: use Analytics Source as fallback with
  reduced confidence.
- No transaction visibility (deals don’t represent transactions and no
  Transaction object): GMV and revenue are gaps; recommend integration
  depth.
- No platform integration: liquidity metrics are gaps; recommend
  integration build.
- Insufficient deal history per side: pattern detection low confidence;
  treat as occasional repeat per side as default.

### Out-of-order events

- Supply or demand status before any signup: data integrity issue.
- Repeat transaction before first transaction: indicates data loading or
  integration issue.
- Side change (contact tagged Supply, then Demand): possible legitimate
  cross-side participation; tag as Both rather than overwriting.
- Deal closed-won with future close date: invalid.

### Source conflicts

Same as other frameworks. Record Source primary; Analytics Source
secondary. For marketplaces specifically, side determination from Record
Source Detail patterns is informative but should be validated against
explicit Side property when available.

### Bad data handling

When pre-flight reliability checks fail at the alarm level, the bot
reports findings as follows:

1.  Side identification coverage gets first priority.
2.  Integration health second.
3.  Then data quality issues per other checks.
4.  Compute Tier 1 metrics (where they remain meaningful without the
    failed check).
5.  Compute Tier 2 metrics with reduced-confidence labels.
6.  Skip Tier 3 metrics that depend on failing checks.
7.  Apply detected per-side retention patterns to interpret
    retention-related metrics conditionally.

Example output structure for a B2C service marketplace:

    Account: Example Service Marketplace
    Pre-flight findings:
      Side identification coverage: WATCH (68% of contacts have side attribution via
        Record Source Detail pattern matching; no explicit Side property)
      Integration health: HEALTHY
      Both sides tracked: HEALTHY
      Deal model clarity: HEALTHY (deals represent transactions; amount = GMV)
      Customer status consistency: WATCH (78%)
      Sufficient deal history for pattern detection: HEALTHY both sides

    Side identification:
      Supply (providers): 4,200 contacts identified
      Demand (customers): 38,400 contacts identified
      Both: 12 contacts (peer-to-peer cross-side participants)
      Unknown: 1,847 contacts (32% of total) - flagged for cleanup

    Retention patterns detected:
      Supply side: Regular repeat (HIGH confidence)
        - Repeat transaction rate: 58%
        - Avg transactions per supplier: 14.2
        - Median time between listings/transactions: 11 days
        - Implication: supply-side retention motion focused on listing optimization
          and supplier success
      Demand side: Occasional repeat (HIGH confidence)
        - Repeat transaction rate: 32%
        - Avg transactions per buyer: 1.7
        - Median time between purchases: 87 days
        - Implication: demand retention via reactivation timed to 60-90 day window;
          reviews and referrals also valuable

    Marketplace stage: Liquidity established
      - Supply-to-demand ratio: 1:9 (healthy for service marketplace)
      - GMV growth (MoM): 8.2%
      - Take rate: 18% (consistent)

    Top recommendations:
      1. Build explicit Side property with workflow population from Record Source
         Detail. 32% of contacts lack side attribution, limiting analytical depth.
      2. Customer status workflow: 22% of customer-side participants with closed-won
         deals not at Customer lifecycle.
      3. Demand reactivation flow: detected 87-day median repeat window; current
         setup has no time-windowed reactivation campaign.

    Reliable metrics (Tier 1, side-segmented):
      Supply: 4,200 active providers; 312 new in last 90 days
      Demand: 38,400 customers cumulative; 2,840 new in last 90 days
      GMV: $1.4M last quarter
      AOV: $89 (consistent)
      Average transactions per supplier: 14.2
      Average transactions per buyer: 1.7

    Conditional metrics (per detected patterns):
      Supply repeat transaction rate: 58% (Regular repeat band)
      Demand repeat transaction rate: 32% (Occasional repeat band, between watch and healthy)
      Supply dormancy threshold: 30 days (per Regular repeat pattern)
      Demand dormancy threshold: 180 days (per Occasional repeat pattern)

    Gap-flagged metrics (Tier 3):
      Time-to-match: cannot compute; no platform integration depth for match events.
      Fill rate: cannot compute.
      Match quality (rating distribution): cannot compute; review system not integrated
        with HubSpot.
      Recommendation: Platform integration extension to expose match events and
        rating data.

    Personalization applied:
      Marketplace stage: Liquidity established
      Supply pattern: Regular repeat
      Demand pattern: Occasional repeat
      Take rate model: Commission only (18%)
      Diagnostic priority: Side attribution cleanup, demand reactivation infrastructure,
        platform integration depth for liquidity metrics.

------------------------------------------------------------------------

End of Marketplace framework.
"""
