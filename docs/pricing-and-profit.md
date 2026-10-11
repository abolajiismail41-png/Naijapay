# Pricing, profit and accounting (Phase 5)

Components kept separate on every sale (all integer kobo, in `pricing_snapshots`, immutable):
provider cost, markup, fee, list price, discount, customer price, referral commission, processing cost,
gross profit (before / after discount), net contribution, margin %.

- **Pricing rules** (`pricing_rules`) are admin-managed and versioned: a change deactivates the old row and adds
  a new one (audited with before/after). Most specific rule wins: scope (network/plan) > provider > tier.
  Methods: PERCENT_MARKUP, FIXED_MARKUP, CUSTOM_PRICE, plus fee, discount, referral %, "cap at face value".
- **Provider cost** comes from `provider_prices`: synced from Inlomax `/services` (6-hourly + admin button), seeded from
  Inlomax's pricing page, `MANUAL` overrides are never overwritten. A SYNCED cost older than 72h blocks new sales.
  Actual cost is read from the provider's `amountCharged` at success; variance >1% is audited.
- **Margin protection**: price < provider cost blocks the sale (customer sees a neutral message, audit row written)
  unless a rule has `allow_subsidy` (SUPER_ADMIN only, reason required).
- **Customers** only ever receive the final price (`/airtime/quote`, transaction views). Cost, markup, margin and profit
  appear only under `/api/v1/admin/*` and need `finance.profit.read` / `pricing.manage`. A test scans customer
  responses for leaked cost fields.

## Ledger (wallet money is never revenue until the provider confirms)
- Hold (at purchase): Dr customer wallet / Cr provider_clearing (price).
- Success: Dr provider_clearing (price) + Dr discounts / Cr sales revenue (price + discount - fee) + Cr service fees;
  Dr provider_cost / Cr provider_float (actual cost); referral: Dr referral_expense / Cr referral_payable.
- Failure: the hold is reversed back to the wallet; revenue is untouched.
- `GET /api/v1/admin/finance/ledger-checks` proves wallets, held funds, revenue, fees and cost agree with
  transaction records, and that the trial balance is zero.

## Dashboard conventions (confirm these match your intent)
- Volume = gross revenue = list price (before discount). Gross profit = revenue - actual provider cost.
- Net contribution = gross profit - discounts - referral commissions - loss on reversed sales - processing cost.
- Pricing preview shows profit AFTER discount (customer price - cost), like your 999.25 / 24.25 / 2.43% example;
  the dashboard shows profit BEFORE discount, then deducts discounts, like your daily example. Both are returned.
- Provider-failed purchases that were refunded never count as sales or losses; they are reported separately.
- Payment-processing cost is `null` until Paystack settlement reconciliation (Phase 13).

## Rounding and scopes (Phase 6)
- `rounding_kobo` on a rule rounds the customer price UP to a multiple (100 = whole naira). Rounding only ever adds margin
  and is recorded in the snapshot's markup. Seeded DATA default: 3.00% markup, whole-naira rounding (placeholder).
- Rule scopes for data, most to least specific: `PLAN:<provider plan id>`, `<NETWORK>:<TYPE>` (e.g. `MTN:SME`), `<NETWORK>`,
  then the category default. Airtime uses `<NETWORK>`.
- Customer plan lists are cached for 60 seconds (public data only, no costs) and the cache is dropped on rule, listing and
  cost-sync changes. Every purchase re-confirms the price anyway.

## FACE_VALUE method and electricity (Phase 7)
`FACE_VALUE`: the customer pays the product value plus the rule's flat fee; markup is whatever the provider discount leaves
(`face - cost`). Electricity default (placeholder, edit it): FACE_VALUE with a NGN 50 fee, scopes `<DISCO>:<PREPAID|POSTPAID>`
then `<DISCO>`. Example at the published 0.5% discount on NGN 5,000: cost 4,975.00, customer pays 5,050.00, gross profit 75.00
(margin 1.49%). The fee is posted to service-fee income, the token value to sales revenue. Tokens are encrypted at rest
(AES-256-GCM, bound to the transaction reference) and returned only by `GET /electricity/{reference}/token` (owner, rate-limited,
audited, never cached).

## Quantity scaling (Phase 8)
Rules price ONE unit (rounding, caps, margin protection) and every component is then multiplied by the quantity, so a fixed
markup is per PIN. Education default (placeholder): FIXED_MARKUP NGN 50 per PIN, whole-naira rounding.
