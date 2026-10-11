# Phase 11 — Referrals and promotions

## Included

- Each authenticated user can obtain a unique `NJP` referral code from `GET /api/v1/referrals/me`.
- Registration accepts optional `referral_code`. Codes are normalized to uppercase, unknown codes and self-referrals are rejected, and one referred user can only be attributed once.
- Referral payout is idempotent and occurs only after the referred user’s first successful qualifying bill purchase. Reward payout is journaled through `REFERRAL_EXPENSE` and `REFERRAL_PAYABLE`, then settled into the inviter’s wallet in the same database transaction as the successful purchase.
- A referral reward amount of zero disables payouts. Configure `REFERRAL_REWARD_KOBO` only after the business reward policy has been approved. `REFERRAL_MIN_PURCHASE_KOBO` is the minimum customer price for the qualifying purchase.
- Admin/finance users with `pricing.manage` can create, list and update promotion campaigns under `/api/v1/admin/promotions`. Campaigns support start/end times, activation, total redemption caps, fixed wallet rewards, and optional minimum successful-purchase qualification.
- Customers can redeem a code at `POST /api/v1/promotions/redeem`. The campaign row is locked while checking its cap; campaign/user uniqueness prevents repeat redemption; the wallet credit, redemption record, notification and ledger journal commit atomically.
- Customer rewards page at `/rewards`; registration includes an optional referral-code field.

## API overview

- `GET /api/v1/referrals/me`
- `POST /api/v1/promotions/redeem` with `{ "code": "WELCOME" }`
- `GET /api/v1/admin/promotions`
- `POST /api/v1/admin/promotions`
- `PATCH /api/v1/admin/promotions/{campaign_id}`

Campaign `reward_kobo` and minimum amounts are integer kobo (₦1 = 100 kobo). Promotion rewards are funded through the existing `platform:discounts` expense account. Referral rewards accrue and settle through the existing referral expense/payable accounts. No client-supplied amount, user ID, wallet ID, or campaign reward is trusted.

## Configuration

```env
REFERRAL_REWARD_KOBO=0
REFERRAL_MIN_PURCHASE_KOBO=50000
```

Keep the referral reward at zero until the amount, qualification, and fraud policy are approved. A referral code by itself does not trigger payment. Promotion campaigns should be created only by authorized staff, with conservative caps and clear terms.

## Important limits

- Promo rewards are wallet credits, not discounts applied to the price of a bill purchase at checkout.
- This phase does not yet implement multi-level referrals, referral cash-outs, campaign analytics/export, anti-abuse device graphing, or a customer-facing admin campaign builder.
- Campaigns with no minimum purchase qualification can be redeemed immediately by any authenticated customer who knows the code; use a minimum qualifying purchase and a total cap for public campaigns.
- Reward eligibility is currently tied to the first successful qualifying bill purchase by the referred account. This does not establish that the account represents a unique human; production rollout still needs abuse controls, monitoring and policy review.
