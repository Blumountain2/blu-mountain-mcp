from ..base import BaseAgent


class EcommerceAgent(BaseAgent):
    """E-commerce vertical agent. FRAMEWORK_TEXT below is Blu
    Mountain's own real, delivered E-commerce framework document,
    embedded verbatim as a Python string constant (openspec/changes/
    vertical-framework-content-in-code) rather than read from Postgres at
    request time via frameworks.store.get_latest() — eliminating the
    "someone forgot to run frameworks.ingest" failure mode entirely, at
    the cost of this content now living in git/the built image (a
    deliberate, explicit tradeoff — see that change's design.md).

    Regenerate this file with scripts/embed_framework_content.py when
    Blu Mountain delivers a revised E-commerce framework document —
    never hand-edit FRAMEWORK_TEXT directly."""

    VERTICAL = "ecommerce"
    SYSTEM_PROMPT_ADDITIONS = ''

    FRAMEWORK_TEXT = r"""# Vertical Framework: E-commerce

Internal reference for the Blu Mountain account analysis system.

## Operating Principles

**Schema first, customization second.** Every HubSpot account ships with
a standard schema. Compute baseline metrics from validated standard
fields for every client. Custom properties, pipelines, and integrations
are enrichments that improve fidelity, not requirements.

**HubSpot is not the source of truth for e-commerce.** The commerce
platform (Shopify, WooCommerce, BigCommerce, Magento, custom) owns
transactions, products, inventory, and customer accounts. HubSpot is the
marketing and CRM layer that consumes synced data. Integration health is
the single most important data quality factor for this vertical. A
broken sync makes every other metric unreliable.

**Trust events, not statuses.** Lifecycle stage is editable and
frequently misused. The bot derives stage from underlying events
(form/list signup, abandoned cart, completed order, repeat order) rather
than from the lifecycle stage property.

**Record Source over Analytics Source.** `hs_object_source` and
`hs_object_source_label` are set automatically and not editable in most
cases. `hs_analytics_source` became editable in 2024. Use Record Source
as primary attribution.

**Customer is at the contact level for B2C; at the company level for B2B
e-commerce.** Most e-commerce is consumer-facing where each customer is
a single contact. B2B e-commerce (industrial supplies, wholesale)
operates more like Transactional with company-level customer status. The
bot detects the operating mode from the data and applies appropriate
aggregation.

**Detect retention pattern, do not assume it.** Most e-commerce
categories are repeat-capable (apparel, beauty, food, supplements), but
some are genuinely one-and-done (mattresses, premium furniture, durables
with multi-year replacement cycles). The bot observes actual repeat
behaviour and applies retention logic conditionally per the same
detection pattern as Transactional.

**Validate before trusting.** Pre-flight reliability checks gate every
metric. The integration health check is added as a first-class concern.

**Personalize by AOV, retention pattern, channel mix, and subscription
overlay.** Channel mix (paid vs owned vs organic) and subscription
presence change recommendations meaningfully.

------------------------------------------------------------------------

## 1. Category Definition

E-commerce businesses sell goods through online catalog-and-checkout
models. Customers browse, add to cart, and purchase without consultative
sales involvement in most cases. Includes direct-to-consumer brands,
online retailers, B2B e-commerce, subscription boxes, replenishment
commerce, and hybrid catalog/marketplace storefronts.

Distinct from Transactional because there is no quote-and-negotiate
sales process; pricing is catalog-fixed. Distinct from Marketplace
because the business is first-party (single seller controlling inventory
and fulfillment) rather than a two-sided platform. Distinct from SaaS
because the product is goods, not software, though subscription overlays
exist (subscription boxes, replenishment).

Hybrid cases are common: an e-commerce business with a subscription tier
inherits from this framework for one-time purchases and from SaaS for
the subscription side. A B2B e-commerce business with custom-quote large
orders inherits from this framework for catalog purchases and
Transactional for quoted deals.

## 2. Common GTM Motion

Marketing is the primary growth lever. Paid acquisition through Meta,
Google, TikTok, and Pinterest dominates for most DTC brands. SEO drives
organic traffic. Email and SMS are the largest owned channels and
typically generate 25-40% of revenue for established brands. Influencer
and affiliate programs supplement.

The customer journey is short and behavioural. Awareness through ad or
content, product page view, cart add, checkout, purchase, often within a
single session for impulse categories or across multiple sessions for
considered purchases. There is no traditional sales cycle.

Post-purchase, owned channels (email, SMS, loyalty) drive repeat
behaviour. Cart abandonment recovery, post-purchase flows, replenishment
reminders, win-back campaigns, and loyalty programs are the standard
motion. Customer service handles returns, exchanges, and product
questions.

## 3. KPIs by Function

### Marketing

ROAS by channel, blended CAC, CAC by channel, attributed pipeline
(sessions, cart adds, purchases), email and SMS revenue contribution,
list growth rate, list engagement (open rate, click rate), creative
performance, attribution model output.

### Conversion (the e-commerce equivalent of sales)

Conversion rate (sessions to purchase), cart abandonment rate, checkout
abandonment rate, average order value, repeat purchase rate, time to
first purchase, time between purchases.

### Customer relationship indicators (presented neutrally; weighting depends on detected retention pattern)

Repeat purchase rate, customer lifetime value, dormancy rate, win-back
rate, NPS, review submission rate, referral rate, subscription rate
(when applicable), loyalty program engagement.

### Service

Order fulfillment time, return rate, exchange rate, support ticket
volume, time-to-resolution, CSAT, refund rate.

The Customer relationship indicators are not all equally weighted. Per
Section 6, the bot detects the retention pattern and emphasizes the
appropriate signals. Most e-commerce categories detect as
repeat-capable, but the framework does not assume this.

------------------------------------------------------------------------

## 4. HubSpot Schema Foundation

Property names verified against HubSpot’s official documentation as
standard. Note: many e-commerce HubSpots also have integration-specific
custom properties (Shopify, WooCommerce, etc.) which the bot identifies
during onboarding analysis but treats as supplementary to standard
schema.

### Contact (always present)

**Identity and ownership**: `createdate`, `hubspot_owner_id`,
`hubspot_owner_assigneddate`, `hs_marketable_status`, `hs_lead_status`,
`lifecyclestage` (treat as unreliable, see Section 5).

**Record Source (primary attribution)**: `hs_object_source`,
`hs_object_source_label`, `hs_object_source_detail_1`,
`hs_object_source_detail_2`, `hs_object_source_detail_3`. For
e-commerce, the most informative Record Source values are FORMS (signup
forms, popups), INTEGRATION (Shopify customer creation, abandoned cart
sync), and CHAT_FLOW. Detail field pattern matching distinguishes
specific signup sources, popup placements, ad campaigns.

**Analytics Source (secondary, editable since 2024)**:
`hs_analytics_source` and related fields. Cross-check only.

**Conversion tracking**: `first_conversion_event_name`,
`first_conversion_date`, `recent_conversion_event_name`,
`recent_conversion_date`, `num_conversion_events`,
`num_unique_conversion_events`. The first conversion type is highly
informative in e-commerce because it distinguishes a list signup from a
cart abandoner from a direct purchaser.

**Engagement signals**: `notes_last_contacted`, `last_activity_date`,
`last_engagement_date`, `hs_email_last_open_date`,
`hs_email_last_click_date`, `hs_email_open` (count of marketing emails
opened), `hs_email_click` (count of marketing emails clicked),
`hs_email_sends_since_last_engagement`. Email engagement is a primary
signal in e-commerce because the email list is a major revenue channel.

**Marketing status**: `hs_marketable_status`, `hs_email_optout`,
`hs_lifecycle_marketingqualifiedlead_date` (informational; not primary).

**Deal association**: `num_associated_deals`. In e-commerce, this
approximates total order count for the customer.

### Company (when present, applies to B2B e-commerce)

`createdate`, `hubspot_owner_id`, `num_associated_contacts`,
`num_associated_deals`, `recent_deal_amount`, `recent_deal_close_date`,
`total_revenue`, `last_activity_date`, `lifecyclestage`, `industry`,
`hs_object_source`, `hs_object_source_label`.

For B2C e-commerce, Company records are often absent or sparsely
populated; customer aggregation happens at the contact level.

### Deal (always present)

**Core**: `createdate`, `closedate`, `dealstage`, `pipeline`, `amount`,
`dealtype`, `hubspot_owner_id`, `num_associated_contacts`. In
e-commerce, deals typically represent orders (one deal per order).

**Close state**: `hs_is_closed`, `hs_is_closed_won`,
`hs_is_closed_lost`, `hs_closed_won_date`, `closed_lost_reason`,
`days_to_close`. Most e-commerce orders create deals already in a
closed-won state (the order completed at creation), so the closed-won
boolean and `closedate` populate at sync time.

**Stage history**: `hs_date_entered_<stageId>`, `hs_v2_*` versions. Less
useful in e-commerce than other verticals because most orders skip
stages.

### Activity

Standard schema. Less central than in sales-led verticals. Email and SMS
engagements (when synced as activities) carry more weight than calls or
meetings. Most e-commerce customers never have a logged human
interaction.

### Custom integration properties

E-commerce HubSpots typically have integration-created custom
properties. Common patterns:

- Shopify integration creates properties on contact and company
  including last order date, total orders, total spent, average order
  value, accepts marketing flag, tags, abandoned cart count.
- Klaviyo, Mailchimp, Drip integrations create email engagement and
  segment membership properties.
- Subscription tools (Recharge, Bold, Skio) create subscription status
  properties.

The bot identifies these during onboarding analysis. They are useful
enrichments but the bot’s baseline metrics rely on standard schema so
the framework works on any e-commerce HubSpot regardless of which
integrations are present.

### What the bot derives from standard schema

| Signal | Schema source |
|:---|:---|
| Acquisition timing | `contact.createdate` |
| Acquisition source | `contact.hs_object_source_label` and detail fields |
| First conversion type | `contact.first_conversion_event_name` |
| List signup | contact created with low-intent Record Source / first conversion |
| Cart abandonment | deal created with stage = Abandoned Cart (when integration creates these) OR contact with first_conversion = checkout_started but no closed-won deal |
| First purchase | contact’s first associated closed-won deal |
| Repeat purchase | contact has more than one closed-won deal |
| Total order count | `contact.num_associated_deals` (proxy when only orders create deals) |
| Customer lifetime value | sum of `deal.amount` for closed-won deals on contact, OR `company.total_revenue` for B2B |
| Last purchase date | max `deal.closedate` for closed-won on contact |
| Days since last purchase | today minus last purchase date |
| Email engagement | `hs_email_open`, `hs_email_click`, `hs_email_last_open_date`, `hs_email_last_click_date` |
| Marketing eligibility | `hs_marketable_status`, `hs_email_optout` |
| AOV (per customer) | avg of `deal.amount` for closed-won on contact |
| AOV (overall) | avg of `deal.amount` across closed-won in period |

------------------------------------------------------------------------

## 5. Data Quality Reality Check

The default assumption: the integration is partially broken or
misconfigured. E-commerce HubSpots have specific failure patterns that
differ from sales-led verticals.

### Properties to treat as unreliable by default

**Lifecycle stage.** Editable, frequently misused. The bot derives
lifecycle from events. E-commerce has a specific failure mode: every
email subscriber gets set to Subscriber lifecycle, every cart abandoner
to Lead, every customer to Customer, but the workflow definitions are
often inconsistent with intent. Some HubSpots set entire imported lists
to Customer prematurely.

**Analytics source.** Editable since 2024.

**Deal amount.** In e-commerce specifically, deal amount handling
depends on the integration: some integrations populate gross order value
(including tax and shipping), others net. Some include refunds and
adjustments, others don’t. The bot validates magnitude consistency and
looks at whether typical deal amounts align with the brand’s stated AOV
range.

**Abandoned cart deals.** When the integration creates abandoned cart
deals as separate records, deal counts and pipeline values inflate. The
bot checks pipeline definition for abandoned cart stages and segregates
these from purchase-pipeline analysis.

**Subscription orders vs one-time.** When a subscription tool creates
separate deals for each renewal cycle, the customer appears to have many
“repeat purchases” that are actually subscription rebills, not new
purchase decisions. The bot identifies subscription deals via
integration property tags or via deal pattern recognition (same amount,
same products, regular intervals).

**Customer status at the contact level.** Multiple contacts on the same
household or order can confuse customer-level reporting. For B2C, the
bot treats each contact as a customer once they have a closed-won deal.
For B2B e-commerce, it operates at the company level.

### Properties to trust by default

Record Source, object timestamps, boolean state flags, engagement
recency, email engagement counts, integration property updates from
healthy syncs.

### Pre-flight reliability checks

| Check | Query | Healthy | Watch | Alarm | Metrics affected if alarm |
|:---|:---|:---|:---|:---|:---|
| Integration health | last sync time of e-commerce platform integration; consistency of order count vs deal count over recent periods | recent and aligned | sync delayed \>24h or counts drifting | sync broken or counts diverging \>10% | All revenue, customer, and order metrics |
| Customer status consistency | % of contacts with at least one closed-won deal that have lifecycle indicating customer status | \>85% | 60-85% | \<60% | Customer count, repeat purchase rate, segmentation |
| Deal amount consistency | variance and pattern of `deal.amount` magnitude | manageable | suspect mixing of gross/net or refunds in scope | mixed conventions | AOV, bookings, LTV |
| Abandoned cart segregation | abandoned cart deals (when integration creates them) tagged or in distinct pipeline | yes | partial | no segregation | Pipeline value, conversion rates |
| Subscription identification | subscription orders distinguishable from one-time via tag, product, or pipeline | yes | partial | no | Repeat purchase rate (inflated by rebills), retention pattern detection |
| Record Source coverage | % of contacts with `hs_object_source_label` populated | \>90% | 70-90% | \<70% | Source attribution, channel mix |
| Email engagement freshness | `hs_email_last_open_date` populated for active subscribers in last 90 days | live data | sparse | absent | Email engagement metrics, list health |
| Active ownership | % of records with `hubspot_owner_id` matching an active user (where owners are used) | \>95% | 85-95% | \<85% | Owner-level reporting (often not applicable in e-commerce) |
| Sufficient deal history for pattern detection | customer cohort age \>12 months OR more than 200 customer contacts with closed-won deals | yes | partial | absent | Retention pattern detection |

### Confidence tiers for e-commerce metrics

**Tier 1 (high confidence, computable from validated standard
schema)**: - Contact volume by Record Source - List growth rate - Email
engagement metrics - Order volume created - Bookings (sum of closed-won
deal amount, when amount is consistent) - AOV - Customer count (distinct
contacts with closed-won) - First-time customer count - Repeat customer
count - Customer lifetime value (per-contact deal-amount sum) - Days
since last purchase

**Tier 2 (medium confidence, requires reliability check pass)**: -
Repeat purchase rate (requires customer status consistency) - True AOV
(requires deal amount consistency, separating gross from net) -
Subscription rate (requires subscription identification) - Source-level
conversion (requires Record Source coverage) - Cart abandonment rate
(requires abandoned cart segregation)

**Tier 3 (requires custom infrastructure or integration depth)**: - ROAS
by channel (requires ad spend integration) - True CAC (requires ad spend
plus attribution) - Cohort LTV curves (requires cohort tracking) -
Channel attribution beyond first-touch (requires multi-touch attribution
platform) - Loyalty program engagement (requires loyalty platform
integration) - Subscription churn (requires subscription tool
integration with churn signals) - Predictive LTV / RFM segmentation
(requires analytics platform or custom build)

------------------------------------------------------------------------

## 6. Retention Pattern Detection

Same approach as Transactional. The bot detects the actual repeat
behaviour from the data and applies retention logic conditionally. For
e-commerce, this matters because most categories are repeat-capable but
some are not.

### Inputs the bot computes

**Repeat purchase rate**: percentage of customer contacts (or companies
for B2B) with more than one closed-won deal. After segregating
subscription rebills from new purchase decisions.

**LTV-to-AOV ratio**: average customer lifetime value divided by average
order value.

**Time between purchases distribution**: for repeat customers, gaps
between consecutive `closedate` values. Median, P25, P75.

**Maximum observed deal-count per customer**: highest number of orders
for any single customer. E-commerce typically shows higher maxima than
Transactional because purchase frequency is higher.

**Customer cohort age**: oldest `contact.createdate` on a customer.

**Subscription share**: when subscription identification is reliable,
percentage of customers with active subscriptions.

### Pattern classification

Same four patterns as Transactional. E-commerce-specific notes:

| Pattern | Detection criteria | E-commerce examples |
|:---|:---|:---|
| One-and-done | Repeat purchase rate \<15% AND LTV-to-AOV ratio \<1.3 | Mattresses, premium furniture, large appliances, considered durables |
| Occasional repeat | Repeat purchase rate 15-40% AND LTV-to-AOV ratio 1.3-2.0 | Apparel for slow-fashion brands, home goods, hobbies, occasional gift purchases |
| Regular repeat | Repeat purchase rate 40-65% AND LTV-to-AOV ratio 2.0-4.0 | Beauty, supplements, food and beverage, fast fashion, consumables |
| High repeat | Repeat purchase rate \>65% AND LTV-to-AOV ratio \>4.0 | Subscription replenishment categories, daily-use consumables, regular reorder behaviour |

### How detected pattern shifts framework application

| Pattern detected | Retention proxy (primary signal) | Recommendation emphasis | Recommendations to NOT make |
|:---|:---|:---|:---|
| One-and-done | Reviews, NPS at delivery, referral attribution, post-purchase satisfaction | Maximize first transaction (AOV via bundling, upsells), capture reviews aggressively, build referral and affiliate motion, optimize delivery experience | Replenishment campaigns, win-back sequences for “lapsed” customers (lapse is the default state) |
| Occasional repeat | Repeat purchase rate, time-between-purchases, AND review/referral metrics | Balanced acquisition and retention. Time campaigns to typical repeat windows. Reviews and referrals remain valuable. | Heavy replenishment automation (timing too unpredictable) |
| Regular repeat | Repeat purchase rate, time between purchases, AOV per repeat order, dormancy rate | Replenishment flows, post-purchase nurture, reorder reminders timed to median repeat window, loyalty program if scale justifies | Acquisition-only focus |
| High repeat | Same as Regular repeat plus subscription opportunity | Subscription conversion offers, retention-style metrics (active customer rate, subscription churn), VIP tier identification, named customer retention motion for top spenders | Treating customers as one-time buyers; under-investing in owned channel infrastructure |

### Subscription overlay

When a subscription tool integration is present and at least 10% of
customers are on subscription, the bot applies SaaS framework principles
to the subscription portion: subscription churn, retention cohort
analysis, expansion (upgrade tiers, add-ons). The one-time-purchase
portion remains under E-commerce framework.

------------------------------------------------------------------------

## 7. Multi-Signal Event Detection

### List signup (Subscriber)

**Primary signal**: contact created with `hs_object_source_label`
indicating list signup (FORMS for popup or footer signup, INTEGRATION
for platform-side signup like Shopify checkout opt-in).

**Secondary signal**: `first_conversion_event_name` matches signup
pattern.

**Cross-checks**: contacts created via IMPORT may be bulk-added
subscribers from a previous platform; segregate from organic signup
cohort.

### Cart abandonment

**Primary signal**: integration creates an Abandoned Cart deal in a
designated pipeline OR contact’s `first_conversion_event_name` indicates
checkout_started without subsequent closed-won deal within typical
purchase window (24-72 hours).

**Secondary signal**: integration property `abandoned_cart_count`
greater than zero.

**Cross-checks**: abandoned carts that later convert to orders should be
linked, not double-counted. The bot checks for closed-won deal on the
same contact within the recovery window.

### Customer (first purchase)

**Primary signal**: contact’s first associated deal where
`hs_is_closed_won` is true and `hs_closed_won_date` is in the past.

**Secondary signal**: integration property indicating first order date
populated.

**Cross-checks**: closed-won with future close date is invalid. For B2B
e-commerce, customer status applies to the company; for B2C, to the
contact.

### Repeat purchase

**Primary signal**: contact (or company) has more than one closed-won
deal where deal createdates are separated by more than typical
session-or-cart proximity (typically 24 hours).

**Secondary signal**: integration property `total_orders` greater than 1
OR similar.

**Cross-checks**: subscription rebills should be excluded from repeat
purchase counting unless the analysis explicitly includes subscription.
Multiple deals created within 24 hours of each other on the same contact
often represent the same order split into multiple SKUs or subscription
items; the bot consolidates these for repeat purchase analysis.

### Subscription enrolment (when subscription overlay applies)

**Primary signal**: subscription tool integration creates or tags a deal
as subscription, OR custom property indicates active subscription
status.

**Secondary signal**: deal has recurring line items (when line items are
synced from the e-commerce or subscription platform).

**Cross-checks**: subscription enrolment should occur on a closed-won
order; orphaned subscription records without an associated order
indicate sync issues.

### Win-back

**Primary signal**: closed-won deal on a customer whose previous
purchase was beyond the dormancy threshold for the detected retention
pattern.

**Secondary signal**: customer enrolled in win-back campaign (when
campaign tracking is set up) at the time of repurchase.

**Cross-checks**: only meaningful when retention pattern is
repeat-capable. For one-and-done detected pattern, win-back is not
flagged.

### Risk

**Primary signal**: subscription customer with cancellation activity,
support ticket spike, return or refund initiated.

**Secondary signal**: drop in email engagement (low open and click rate
over 90 days for previously engaged subscriber), low NPS or negative
review.

**Cross-checks**: risk in e-commerce is most actionable for subscription
customers and high-LTV repeat customers. For occasional or one-and-done
customers, risk signals are less actionable.

### Dormancy

The bot computes days-since-last-purchase universally. Interpretation is
conditional on detected pattern, same as Transactional:

- One-and-done: dormancy is the default. Not flagged.
- Occasional repeat: dormancy beyond median time-between-purchases is a
  recirculation candidate.
- Regular repeat: dormancy beyond P75 is a clear lapse; reactivation
  campaign appropriate.
- High repeat: dormancy beyond typical interval is a strong risk signal.

------------------------------------------------------------------------

## 8. Lifecycle Model

E-commerce lifecycle differs from sales-led verticals because there is
typically no MQL or SQL stage. The funnel is more behavioural and
shorter.

### Canonical lifecycle (event-derived)

| Stage | Derived from | Event detection |
|:---|:---|:---|
| Subscriber | List signup, no purchase intent yet | Form/popup submission, footer signup, opt-in checkbox at checkout (for non-purchasers), profile created without purchase |
| Lead | Captured contact above subscriber intent | Cart added, checkout started, account created with intent signal |
| Opportunity | High-intent abandonment | Checkout abandoned, multiple session visits to product pages, wishlist add, recurring cart adds |
| Customer | First purchase | Closed-won deal associated to contact |
| Repeat customer | Subsequent purchase | Second or later closed-won deal (after consolidating same-cart splits) |
| Subscriber-of-subscription | Active subscription | Subscription tool indicates active enrollment |
| VIP | High LTV, high frequency, or top-tier loyalty status | Customer LTV above P95 OR loyalty program top tier (when integration present) |
| Evangelist | Referral source or strong advocate | Referral attribution OR very high NPS plus public review |
| Dormant | Customer with no activity past pattern-appropriate threshold | Conditional per detected retention pattern |

The MQL and SQL stages from the SaaS canonical lifecycle do not apply in
pure e-commerce. The bot does not attempt to map them. If the client has
populated MQL or SQL on contacts in their HubSpot, this is typically an
artifact of using a HubSpot template designed for B2B SaaS; the bot
reports this as a likely lifecycle misconfiguration.

### Mapping client-specific stages

E-commerce HubSpots often use lifecycle stages in non-standard ways:

- “Customer” used for anyone who created an account, not just
  purchasers - flag as inflation
- “Marketing Qualified Lead” used for engaged email subscribers - this
  is a misuse but common; map to Subscriber or Lead
- “Sales Qualified Lead” used for cart abandoners - map to Lead or
  Opportunity
- “Opportunity” used for high-intent unconverted - map to Opportunity
- “Evangelist” used for repeat customers - map to Repeat customer or
  Evangelist depending on signal strength

The bot reports the mapping it applies and flags likely misuse cases.

### Why traditional B2B lifecycle does not fit

E-commerce has no sales process. There is no MQL because there is no
sales handoff, no SQL because there is no sales rep qualifying. Treating
an engaged email subscriber as MQL is a metaphor that breaks reporting
in any tool that expects standard MQL semantics. The bot’s derived
lifecycle uses behavioural stages that match how e-commerce actually
works and reports the client’s lifecycle stage values as informational
only.

------------------------------------------------------------------------

## 9. Business Model

**Name**: E-commerce

**Inclusion rules**: - Revenue is order-based through online catalog
purchase - Pricing is catalog-fixed, no quote-and-negotiate process for
the standard motion - Sales cycle is short (usually session-based, hours
to days) - Marketing is the primary growth lever - Most customers do not
interact with a sales rep - Fulfillment is by the seller (first-party)

**Exclusion rules**: - Quote-and-negotiate B2B with consultative sales
motion maps to Transactional - Two-sided supply-and-demand platform maps
to Marketplace - Subscription-only revenue (no one-time purchase option)
maps to SaaS framework - Project-based custom delivery maps to Services
framework

**Hybrid handling**: e-commerce with a subscription tier inherits SaaS
framework for the subscription portion. B2B e-commerce with custom-quote
large orders inherits Transactional for quoted deals.

**Revenue trigger**: closed-won deal originating from the e-commerce
platform integration (most reliably identified via Record Source =
INTEGRATION with platform identifier in detail field).

------------------------------------------------------------------------

## 10. Funnel and Core Events

### Funnel stages

| Stage | Detection signal |
|:---|:---|
| List signup | Form/popup submission, opt-in checkbox at checkout, footer subscription |
| Engaged subscriber | Email opens or clicks within 30 days |
| Cart abandonment | Cart created but not purchased OR checkout started without completion |
| First purchase | First closed-won deal |
| Repeat purchase | Second+ closed-won deal (after subscription rebill exclusion when applicable) |
| Subscription enrolment | Active subscription signal |
| Lapsed (conditional) | No purchase past pattern-appropriate threshold |
| VIP | Top-tier customer by LTV or loyalty status |

### Core events

Acquisition: list signup or first contact created. Activation: cart
added or first purchase, depending on motion. Conversion: first
purchase. Repeat: subsequent purchase. Subscription enrolment:
subscription started (when applicable). Lapse: dormancy past
pattern-appropriate threshold (conditional). Risk: subscription
cancellation intent, service issue, low engagement on previously engaged
subscriber.

### Event detection signals matrix

| Event | Form | Property Change | Object Creation | Activity | Product / External |
|:---|:---|:---|:---|:---|:---|
| List signup | Newsletter / popup form | Lifecycle to Subscriber (auto via workflow, treat as informational) | New Contact with Record Source = FORMS | – | E-commerce platform integration sync of subscriber |
| Cart abandonment | – | Abandoned cart deal stage, custom property update | New Abandoned Cart deal (when integration creates) | – | E-commerce platform sync of cart event |
| First purchase | – | `hs_is_closed_won` = true on first deal | New closed-won deal | – | E-commerce platform sync of order completion |
| Repeat purchase | – | Customer already has prior closed-won deal | New closed-won deal on existing customer | – | E-commerce platform sync |
| Subscription enrolment | Subscription form (when used) | Subscription status property set to active | Subscription record (when integration creates) | – | Subscription tool sync |
| Win-back | – | – | New closed-won on previously dormant customer | – | E-commerce platform sync |
| Lapse / dormancy (conditional) | – | Days since last purchase exceeds pattern threshold | – | – | – |
| Risk | NPS detractor | Subscription cancellation request property | Support ticket | Refund / return logged | Subscription tool churn signal, return management system |

------------------------------------------------------------------------

## 11. KPI Logic

### Acquisition and List Health

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| List growth rate | 1 | net new subscribers / starting list size | new contacts in period minus opt-outs in period, divided by start-of-period count | rolling monthly |
| Acquisition by Record Source | 1 | count grouped by source | `count(contact) where createdate in [period]` group by `hs_object_source_label` | rolling, requires Record Source coverage check pass |
| Acquisition by Record Source Detail | 1 | count grouped by detail | group by `hs_object_source_detail_1` | granular into specific signup form or campaign |
| List engagement (open rate, last 30d) | 1 | contacts with `hs_email_last_open_date` in last 30d / active marketable contacts | derived | rolling |
| List engagement (click rate, last 30d) | 1 | contacts with `hs_email_last_click_date` in last 30d / active marketable contacts | derived | rolling |
| Sends since last engagement (avg) | 1 | avg of `hs_email_sends_since_last_engagement` for marketable contacts | direct | live |
| Subscriber-to-customer conversion | 1 | subscribers who purchase / subscriber cohort | contacts who have a closed-won deal whose deal createdate is after contact createdate | 90 days, 365 days from createdate |

### Conversion and Sales

| KPI | Tier | Formula | Schema Query | Lookback |
|:---|:---|:---|:---|:---|
| Order volume | 1 | count of closed-won deals | `count(deal where hs_is_closed_won and closedate in [period])` | rolling |
| Bookings (gross) | 2 | sum of closed-won deal amount | `sum(deal.amount) where hs_is_closed_won and closedate in [period]` | requires deal amount consistency |
| AOV | 2 | avg of closed-won deal amount | `avg(deal.amount) where hs_is_closed_won and closedate in [period]` | requires deal amount consistency |
| Cart abandonment rate | 2 | abandoned carts / total cart starts | requires abandoned cart segregation | rolling |
| Subscriber-to-purchase time | 1 | days from contact createdate to first closed-won deal | per cohort | 30/60/90/180 days |
| New customer count | 1 | distinct first-time customers | contacts whose first closed-won deal is in period | rolling |
| Conversion rate (sessions to purchase) | 3 | purchases / sessions | requires session data via integration | rolling |
| Email/SMS revenue contribution | 3 | revenue attributed to email/SMS / total revenue | requires attribution from email/SMS platform | rolling |

### Customer Relationship Indicators

The bot computes all of these regardless of pattern; reporting
interpretation is conditional per Section 6.

| KPI | Tier | Formula | Schema Query | Conditional interpretation |
|:---|:---|:---|:---|:---|
| Customer count (cumulative) | 1 | distinct contacts (or companies for B2B) with at least one closed-won deal | `count(distinct contact where exists closed-won deal)` | Universal |
| Repeat customer count | 1 | distinct contacts with more than one closed-won deal (after subscription consolidation) | derived | Universal; interpretation depends on pattern |
| Repeat purchase rate | 2 | repeat customers / total customers | requires customer status consistency | Primary for occasional/regular/high repeat; informational for one-and-done |
| Time between purchases (median, P25, P75) | 2 | distribution of gaps between consecutive closedates per customer | derived | Primary input for retention pattern detection |
| LTV (per customer) | 1 | sum of `deal.amount` for closed-won on contact | derived | Universal |
| LTV (avg) | 1 | mean of per-customer LTV | derived | Universal |
| LTV-to-AOV ratio | 1 | avg LTV divided by avg AOV | derived | Primary input for retention pattern detection |
| Days since last purchase | 1 | today minus last closed-won closedate per customer | live | Universal computation; interpretation per pattern |
| Dormancy rate (conditional) | 2 | customers exceeding pattern-appropriate dormancy threshold | requires threshold per pattern | Meaningful only for occasional/regular/high repeat |
| Win-back rate | 2 | dormant customers who repurchased in period / dormant pool at period start | requires dormancy tracking | Meaningful only for repeat-capable patterns |
| Subscription rate | 2 | active subscription customers / total customers | requires subscription identification | Universal when subscription is part of business |
| Referral attribution | 3 | customers attributed to existing customer referrals | requires referral tracking | Primary for one-and-done; useful for all |
| Review submission rate | 3 | reviews submitted / orders | requires review platform integration | Primary for one-and-done; useful for all |

### Marketing Efficiency (Tier 3 unless noted)

| KPI | Tier | Requirement |
|:---|:---|:---|
| ROAS by channel | 3 | Ad spend integration |
| Blended CAC | 3 | Total ad spend divided by new customer count, requires spend integration |
| CAC by channel | 3 | Ad spend integration plus attribution |
| LTV / CAC ratio | 3 | Both LTV and CAC computable |
| Payback period | 3 | LTV curve plus CAC |

------------------------------------------------------------------------

## 12. AOV-Based Personalization

The bot adjusts recommendations based on AOV, detected retention
pattern, channel mix, and subscription overlay.

### What the bot looks up per client

**Median AOV**: median of `deal.amount` across closed-won deals in
trailing 12 months.

**AOV distribution**: P25, P50, P75, P95.

**Detected retention pattern**: per Section 6.

**Channel mix**: estimated from Record Source Detail and integration
data. Distinguishes paid-heavy (most acquisition from paid channels)
from owned-heavy (email, SMS, organic, referral) businesses.

**Subscription overlay**: present (\>10% of customers on subscription)
or absent.

**Top-10 customer concentration**: usually low for pure B2C e-commerce
(no single customer concentration); higher for B2B e-commerce.

### AOV bands

| Band | AOV Range | Motion | Recommendation emphasis (universal across patterns) |
|:---|:---|:---|:---|
| Impulse | \<\$30 | Very high volume, paid-heavy, mobile-first | AOV optimization (bundles, free shipping thresholds, upsell at checkout), high-frequency email, SMS, fast cart recovery |
| Mid-impulse | \$30 - \$100 | High volume, mixed paid and owned | Cart abandonment recovery, post-purchase flows, email engagement, repeat-window timing (per pattern), product education content |
| Considered | \$100 - \$500 | Medium volume, considered purchase, mixed channels | Multi-touch nurture, cart abandonment recovery with depth, social proof, post-purchase NPS, quality content |
| High-consideration | \$500 - \$2K | Lower volume, longer consideration, owned channels critical | Educational content, multi-touch nurture, social proof and reviews, post-purchase satisfaction, expand into adjacent products |
| Premium | \$2K+ | Low volume, highly considered | Concierge-style customer experience, white-glove delivery, named account management for top customers, brand and lifestyle marketing |

### Conditional retention emphasis (per detected pattern)

Same logic as Transactional, applied to e-commerce specifics:

- **One-and-done detected**: emphasize first-purchase AOV maximization
  (bundling, upsells), post-delivery NPS, review and referral capture,
  customer experience optimization. Do not recommend replenishment
  campaigns or lapsed-customer reactivation.
- **Occasional repeat detected**: balance acquisition with reactivation
  timed to median repeat window. Reviews and referrals remain valuable.
- **Regular repeat detected**: emphasize replenishment flows,
  post-purchase nurture, reorder reminders, loyalty program if scale
  justifies. Reviews secondary.
- **High repeat detected**: VIP tier identification, subscription
  conversion offers if subscription overlay applies, retention-style
  metrics, named customer retention motion for top spenders.

### Channel mix overlay

**Paid-heavy** (\>60% of new customer acquisition from paid channels)
requires emphasis on ROAS discipline, blended CAC management,
attribution accuracy, creative refresh cadence. Diversification
recommendations to grow owned channels become priority.

**Owned-heavy** (\>50% from email, SMS, organic, referral) is healthier
from a CAC perspective but indicates limited acquisition scale.
Recommendations include paid channel testing, list growth investment,
content investment.

**Balanced** (no channel above 50%) is the healthiest profile;
recommendations focus on optimization within each channel.

### Subscription overlay

When \>10% of customers are on subscription:

- Apply SaaS framework principles to subscription portion (subscription
  churn, retention cohort analysis, expansion).
- Subscription conversion rate (one-time customer to subscription)
  becomes a primary funnel metric.
- LTV calculation segments subscription LTV separately from one-time
  LTV.

------------------------------------------------------------------------

## 13. Benchmarks

E-commerce benchmarks vary widely by category, AOV band, and channel
mix. Sources include Klaviyo benchmarks, Shopify reports, Pipe17
industry studies, Common Thread Collective benchmarks. Replace with
Blu’s authoritative benchmarks when ingested.

### Acquisition and List

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| List growth rate (monthly) | \>5% | 2-5% | \<2% or declining | Net of opt-outs; varies with paid investment |
| Subscriber-to-customer conversion (90d) | \>5% | 2-5% | \<2% | Higher for impulse AOV, lower for high-consideration |
| Email engagement (30d active openers) | \>25% of marketable | 15-25% | \<15% | Active openers as % of marketable list |
| Email click rate (30d) | \>2% | 1-2% | \<1% | Industry varies; track trend |
| Sends since last engagement (avg) | \<3 | 3-6 | \>6 | Above 6 indicates list sunset needed |

### Conversion and Sales

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Cart abandonment rate | \<70% | 70-80% | \>80% | Industry average around 70%; aspirational \<60% |
| Conversion rate (sessions to purchase) | \>2.5% | 1.5-2.5% | \<1.5% | Site-level; varies with traffic source |
| Subscriber-to-purchase time (median) | \<14 days | 14-45 days | \>45 days | First-time buyers from list signup |
| AOV trend | growing or stable | flat | declining | Track quarter over quarter |

### Customer Relationship (conditional per detected pattern)

| Metric | Pattern | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|:---|
| Repeat purchase rate | One-and-done | – | – | – | Informational only |
| Repeat purchase rate (90d) | Regular repeat | \>25% | 15-25% | \<15% | First repeat within 90 days for fast-cycle category |
| Repeat purchase rate (180d) | Occasional repeat | \>25% | 15-25% | \<15% | First repeat within 180 days |
| Repeat purchase rate (365d) | All repeat patterns | \>40% | 25-40% | \<25% | Annual repeat for the customer base |
| Time between purchases (median) | Pattern-dependent | – | – | – | Used to calibrate repeat window for campaigns |
| LTV / AOV ratio | Pattern-dependent | – | – | – | Pattern detection input, not a benchmark |
| Subscription rate (when applicable) | Subscription overlay | \>15% of customers | 5-15% | \<5% (when subscription is offered) | Indicates subscription program traction |
| Subscription churn (when applicable) | Subscription overlay | \<5% monthly | 5-10% | \>10% | Apply SaaS retention benchmarks for subscription portion |
| Referral share of new customers | All; primary for one-and-done | \>15% | 5-15% | \<5% | Direct referrals tracked through referral program or attribution |
| Review submission rate (when integrated) | All; primary for one-and-done | \>10% of orders | 3-10% | \<3% | Post-purchase review request flow |

### Marketing Efficiency (when measurable)

| Metric | Healthy | Watch | Alarm | Notes |
|:---|:---|:---|:---|:---|
| Email/SMS revenue contribution | 25-40% | 15-25% | \<15% | Of total revenue; healthy DTC brands often hit 30-40% |
| Blended ROAS (paid acquisition) | \>3x | 2-3x | \<2x | Varies enormously by category; track trend |
| LTV / CAC ratio | \>3.0 | 1.5-3.0 | \<1.5 | Below 1.5 means unit economics are broken |
| First-order CAC payback | within 3-6 months | 6-12 months | \>12 months | Faster payback for repeat-capable patterns; slower acceptable for high LTV |

### Maturity stage adjustments

| Stage | Revenue range | Diagnostic priority | Benchmark adjustments |
|:---|:---|:---|:---|
| Early DTC | \<\$1M | List growth, first-order conversion, paid channel testing | Loose benchmarks; channel mix typically heavily paid |
| Growth DTC | \$1M - \$10M | Email/SMS infrastructure, post-purchase flows, AOV optimization, retention pattern detection becoming reliable | Standard benchmarks apply |
| Scale DTC | \$10M - \$50M | Cohort LTV analysis, subscription consideration, channel diversification, loyalty programs | Tighter benchmarks; subscription overlay common |
| Mature DTC | \$50M+ | Margin discipline, channel diversification beyond paid social, retention sophistication, brand investment | Mature DTC benchmarks; CAC payback discipline critical |

------------------------------------------------------------------------

## 14. Required Data Minimum

**Identity**: email plus contact ID. For B2B e-commerce, also company
domain.

**Source**: `hs_object_source_label` populated on at least 70% of
contacts. Detail field discipline matters because attribution drives
marketing efficiency analysis.

**Event timestamps**: contact `createdate`, deal `createdate` and
`closedate`, email engagement timestamps.

**Revenue value**: `deal.amount` populated on closed-won deals with
consistent magnitude convention (gross or net consistent across deals).

**Activity / engagement signal**: at least one of
`hs_email_last_open_date`, `last_engagement_date` populated for active
subscribers.

**Marketing eligibility**: `hs_marketable_status` and `hs_email_optout`
populated.

**Customer status consistency**: `lifecyclestage` set to Customer on at
least 85% of contacts (or companies for B2B) with associated closed-won
deals.

**Integration health**: e-commerce platform integration syncing
reliably. Order count from platform should match deal count in HubSpot
within tolerance (5-10%) over recent periods.

**For confident retention pattern detection**: customer cohort age \>12
months OR more than 200 customer contacts with closed-won deals tracked.

When any required floor is missed, the bot reports the gap as the
highest-priority finding before analyzing anything else. For e-commerce
specifically, integration health is reported first because nothing else
works without it.

------------------------------------------------------------------------

## 15. Rules and Edge Cases

### What happens when each event occurs

**List signup**: Record Source captured automatically, lifecycle
workflow may set Subscriber, marketing automation sequence triggered,
suppression list checks.

**Cart abandonment**: cart abandonment flow triggered (typically series
of 2-3 emails over 24-72 hours), possibly with discount escalation.
Window for measurable recovery is short.

**First purchase**: lifecycle workflow sets Customer, post-purchase flow
triggered (order confirmation, shipping updates, delivery confirmation,
NPS request, review request).

**Repeat purchase**: customer LTV updated automatically via deal sum;
loyalty program engagement may be tracked. Interpretation conditional on
detected pattern.

**Subscription enrolment**: subscription tool tracks separately; HubSpot
sync updates subscription status property; SaaS framework principles
apply to subscription portion.

**Lapse / dormancy**: action conditional on detected pattern.
Repeat-capable patterns trigger reactivation campaign eligibility;
one-and-done detected patterns do not flag lapse.

**Risk** (subscription cancel intent, refund initiated, repeat support
tickets): alert to retention or service team.

### Duplicate handling

- Contacts: dedupe by email primary. For B2C, secondary by phone when
  present. For B2B e-commerce, also by company domain plus name.
- Companies: dedupe by domain primary; less commonly populated in B2C
  e-commerce.
- Deals: same-cart splits (multiple deals from one order) should be
  consolidated for repeat purchase analysis. The bot uses 24-hour
  proximity plus same contact as the merge heuristic. Subscription
  rebills should be flagged separately from new purchase decisions.

### Missing signals

- No Record Source captured: use `hs_analytics_source` as fallback with
  reduced confidence.
- Integration sync gaps: bot reports the gap and excludes affected
  period from metrics until sync recovers.
- No deal amount at close: flag for review, exclude from AOV and
  bookings rollup.
- No `hs_marketable_status`: assume marketable for active contacts; flag
  for proper population.
- No subscription identification (when subscription overlay should
  apply): repeat purchase rate inflated by rebills; flag and recommend
  subscription tagging.
- Insufficient deal history for pattern detection: report low-confidence
  detection and treat as occasional repeat by default.

### Out-of-order events

- Customer status before any deal: lifecycle abuse, not real customer
  status.
- Repeat purchase before first purchase: data integrity issue (often
  caused by subscription rebill mistakenly tagged as the first order).
- Multiple closed-won within minutes on the same contact: same-cart
  split; consolidate.
- Closed-won with future close date: invalid, flag.

### Source conflicts

Same as other frameworks. Record Source primary; Analytics Source
secondary; trust Record Source on conflict. For e-commerce specifically,
Record Source = INTEGRATION with Shopify (or other platform) is the most
common source for purchase contacts and may obscure original marketing
source. Recommend integration configuration that captures original
marketing source as a separate property where possible.

### Bad data handling

When pre-flight reliability checks fail at the alarm level, the bot
reports findings as follows:

1.  Lead with the data quality issue (integration health gets priority
    for e-commerce).
2.  Compute Tier 1 metrics and report with confidence.
3.  Compute Tier 2 metrics with reduced-confidence labels.
4.  Skip Tier 3 metrics that depend on the failing check.
5.  Apply detected retention pattern to interpret retention-related
    metrics conditionally.

Example output structure for a beauty DTC brand:

    Account: Example Beauty Co
    Pre-flight findings:
      Integration health: WATCH (Shopify sync delayed 6h, deal count vs platform order
        count diverging 3% in last 14 days)
      Customer status consistency: HEALTHY (94% of customers correctly tagged)
      Deal amount consistency: HEALTHY
      Record Source coverage: HEALTHY (96%)
      Subscription identification: HEALTHY (Recharge tags applied)
      Sufficient deal history for pattern detection: HEALTHY (32-month customer cohort,
        14,200 customer contacts)

    Retention pattern detected:
      Pattern: Regular repeat
      Confidence: HIGH
      Repeat purchase rate (180d): 38%
      Repeat purchase rate (365d): 56%
      LTV-to-AOV ratio: 2.8
      Median time between purchases: 67 days
      Subscription overlay: 18% of customers on Recharge subscription (active)
      Implication: retention motion focuses on replenishment flows, post-purchase nurture,
        subscription conversion offers; reviews and referrals remain useful but secondary

    Top recommendations:
      1. Replenishment flow optimization: time email/SMS reorder reminders to 50-60 days
         post-purchase (P25 of time-between-purchases). Currently no replenishment flow
         detected; this is the highest-leverage retention motion for the detected pattern.
      2. Subscription conversion offers: 18% subscription rate is room to grow. Test
         subscription offers in post-purchase email flow for repeat customers.
      3. Investigate Shopify sync delay: 6h delay and 3% count divergence. Check
         integration logs.

    Reliable metrics (Tier 1):
      List size: 187,400 marketable contacts
      List growth (monthly): 7.2%
      Email engagement (30d active openers): 31%
      Order volume: 4,820 last 30 days
      AOV: $58
      Customer count (cumulative): 22,100
      Repeat customer count: 8,640
      Avg LTV: $164

    Conditional metrics (per detected pattern):
      Repeat purchase rate (180d): 38% (Regular repeat band, between healthy and watch)
      Days since last purchase per customer: median 71d, P75 156d
      Dormancy rate (P75 threshold): 24% of customers (Regular repeat lens)

    Gap-flagged metrics (Tier 3):
      ROAS by channel: cannot compute. No ad spend integration.
      Recommendation: Triple Whale, Northbeam, or similar attribution platform.
      Cohort LTV curves: cannot compute without cohort tracking infrastructure.

    AOV personalization applied:
      Median AOV: $58 (Mid-impulse band)
      P25-P75 range: $42 to $84
      Detected retention pattern: Regular repeat
      Channel mix: Paid-heavy (estimated 65% paid acquisition from Record Source Detail)
      Subscription overlay: present (18%)
      Diagnostic priority: Replenishment flow build, subscription growth, channel
        diversification toward owned, integration sync investigation.

------------------------------------------------------------------------

End of E-commerce framework.
"""
