# Inlomax integration notes (from https://inlomax.com/docs)

- Auth `Authorization: Token <key>`; purchase `POST /airtime {serviceID, amount, mobileNumber, request-id}`;
  status `POST /transaction {reference}` (Inlomax's reference only); `GET /balance`, `GET /services`.
- We send our transaction reference as `request-id`. Purchases are NEVER retried by us.
- Only an explicit `status: failed` from Inlomax refunds. Timeouts, 5xx, unparseable or unknown statuses are UNKNOWN:
  funds stay held, the sweeper re-verifies when we have Inlomax's reference, otherwise finance resolves manually.
- Webhooks are unsigned in the docs: the URL carries a secret token and the body is only a hint; the real status is
  always re-fetched from the API before any state change.

## Questions to put to Inlomax in writing before go-live
1. Is `request-id` de-duplicated (is a repeat of the same request-id rejected or returned as the original)?
2. Can a transaction be looked up by `request-id`? Today a timeout before we receive their `reference` cannot be auto-resolved.
3. The airtime sample response shows the key `reference` twice with different values: which one is queryable?
4. Can webhooks be signed (HMAC) or IP-restricted? Which source IPs?
5. Exact airtime min/max amounts, rate limits, and the sandbox's failure/pending simulations.
6. Written API rate sheet (airtime discount % per network), notice period for rate changes, and an SLA.
7. How are provider-side reversals credited to our float, and how fast?

## Data bundles (Phase 6)
- Purchase `POST /data {serviceID, mobileNumber, request-id}`. Plans come from `GET /services` (`dataPlans`: serviceID, network,
  dataPlan, dataType, validity, amount). The current services page could not be re-opened when this was built, so the parser
  accepts both documented shapes and skips malformed rows; verify against the sandbox before go-live.
- Provider cost for a plan is its listed `amount`. The purchase response's `amount` is treated as the actual cost (data has no
  face value); a variance of more than 1% from the quoted cost is audited as `transaction.settlement_flags`.
- New plans are discovered UNLISTED. An admin must price and list each one (listing is refused if there is no fresh cost or the
  price would be below cost). Plans that vanish from the provider are retired, unless most of the catalogue vanishes at once
  (treated as a bad sync: nothing is deactivated and an audit alert is written).

### Extra questions for Inlomax
8. Is `request-id` honoured on `/data` (their homepage sample omits it; their SDK sends it)?
9. In a data purchase response, is `amount` our cost, the customer price, or the plan size in MB?
10. What happens to data sent to a wrong-network number (refundable?), and is there a number/network validation endpoint?
11. Plan removal/price-change notice period, and whether plan serviceIDs are stable over time.

## Electricity (Phase 7) - NOT YET VERIFIED AGAINST INLOMAX
I could not retrieve Inlomax's electricity documentation. The adapter follows the field names in their official PHP SDK
(`verifyMeter {meterNumber, disco}`, `buyElectricity {serviceID, amount, meterNumber, request-id}`); the two endpoint paths
(`/validatemeter`, `/electricity`), the response shapes, how tokens are returned and how the catalogue lists DISCOs are
assumptions. Safeguards:
- With `BILL_PROVIDER=inlomax` electricity is OFF (`INLOMAX_ELECTRICITY_ENABLED=false`) until you turn it on after testing in
  their sandbox. The sandbox provider always works.
- Paths are settings. The DISCO catalogue and its provider mapping (disco code, prepaid/postpaid service ids, discount) can be
  entered or corrected by hand in the admin API, so a wrong sync guess never blocks you.
- Unclear validation answers are "provider unavailable", never "invalid meter"; unclear purchase answers are UNKNOWN.
- A confirmed sale without a token is settled, flagged (`transaction.token_missing`), retried by the sweeper for ~12 attempts,
  then escalated (`transaction.secret_unrecoverable`) for manual recovery.
Please paste the Inlomax electricity page (verify + purchase + services listing) and I will finish the adapter exactly.

### Extra questions for Inlomax
12. Meter verification endpoint, request fields (disco vs serviceID), response fields, and whether it returns minimum amount.
13. Purchase response: where is the token, units, and the amount actually charged? Is the token also available by status lookup?
14. Do prepaid and postpaid have separate serviceIDs? Is there a vend minimum/maximum and a vend lock per meter?
15. What happens when a meter is vended twice within seconds (duplicate protection by request-id)?

## Data-protection note
Meter validation shows the meter holder's name and address so the customer can confirm the meter. That is personal data about
a third party: validation is rate-limited per user (10/hour, 40/day), audited with the meter number masked, and bound to the
requesting user for 15 minutes. Have counsel confirm the lawful basis and notice wording (NDPA).

## Exam pins (Phase 8) - from https://inlomax.com/docs/edu
- `POST /education {serviceID, quantity, request-id}`; success returns `data.pins[] = {pin, serialNo}` (values are padded with
  spaces: we trim them), `educationType`, `quantity` (a string) and `amount`. The documented sample has NO `reference`, so a
  later status lookup is impossible unless Inlomax returns one: a timeout therefore needs manual resolution, and missing or
  partial pins can only be recovered if the provider adds a reference.
- `amount` is treated as our total cost for the purchase. Because its meaning (total vs per pin) is not documented, a
  reported cost more than 25% from the quote is NOT booked: the quoted cost is booked instead and the sale is flagged
  `cost_untrusted` for review.
- Products and costs are entered by an admin (`/api/v1/admin/education/products`): the services listing for exam pins could
  not be verified. Sold at markup: placeholder is a NGN 50 FIXED markup per pin (WAEC 5,170 -> 5,220, under the 5,250 retail).
  Percent and per-product rules work too (`PRODUCT:<service id>` beats the exam code beats the default).
- PINs are encrypted at rest (AES-256-GCM bound to the transaction) and returned only by `GET /education/{reference}/pins`
  (owner-only, rate-limited, audited, never cached). Partial deliveries are shown and escalated; missing ones are retried.

### Extra questions for Inlomax
16. Does the education response include a `reference` (or can we query by `request-id`)? Without one we cannot verify or recover.
17. Is `amount` the total charged or the unit price? How are quantities above 1 priced?
18. Service IDs, current API prices and min/max quantity per exam (WAEC, NECO, others); is the listing in `/services`?
19. Are we authorised to resell result-checker PINs (WAEC/NECO terms), and what is the replacement process for an invalid PIN?


## TV subscriptions (Phase 9) - VERIFY MAPPINGS BEFORE LIVE USE
- Official docs describe `POST /validatecable` with `{serviceID, iucNum}` and `POST /subcable` with `{serviceID, iucNum, request-id}`. `/services` exposes `cablePlans` with package service IDs, operator names, package names, amounts and discounts.
- The provider's examples use a validation `serviceID` and package IDs in different contexts. NaijaPay therefore stores `provider_operator_id` separately from `provider_service_id`; never assume these IDs are interchangeable.
- TV is disabled for `BILL_PROVIDER=inlomax` by default (`INLOMAX_TV_ENABLED=false`). Enable only after confirming validation and purchase IDs, request body, success/failure/pending responses, and status lookup against the provider sandbox. The local sandbox adapter is available independently.
- Products and verified provider costs are configured through `/api/v1/admin/tv/products`. Products begin unlisted. The price engine applies the `TV` category pricing rule, and listing requires a valid sell price above cost.
- TV purchase requests are not retried by the adapter. A timeout or unrecognised response stays `UNKNOWN`; a definite provider failure follows the existing refund path.

### Questions for Inlomax TV
20. Is `serviceID` for `/validatecable` the operator/biller ID while `/subcable` expects the bouquet/package ID? Please provide the authoritative ID mapping.
21. Does `/subcable` return a stable provider transaction reference that `/transaction` can query? Is `request-id` deduplicated?
22. Does the `amount` in a cable purchase response mean total cost debited from reseller float? Are discounts reflected there?
23. Which cable operators/packages are active in the account, and what are the validation/purchase sandbox test cases for invalid IUC, processing, failed and timeout outcomes?
