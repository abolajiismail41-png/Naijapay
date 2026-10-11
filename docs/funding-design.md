# Wallet funding (Phase 4)

Flow: quote -> POST /wallet/funding (Idempotency-Key) -> customer pays on Paystack -> webhook and/or poll ->
worker verifies with Paystack -> one ledger journal credits the wallet.

Rules enforced in code and tests:
- The wallet is credited only after the processor's verify API confirms: reference, currency (NGN) and the
  exact charged amount (credit amount + fee). Any difference becomes MISMATCH (no credit, audited, finance review).
- Webhooks: HMAC-SHA512 over the raw body, constant-time compare, stored once (unique source + event key),
  acknowledged immediately, processed by a worker. Duplicate deliveries are no-ops.
- Unknown outcomes (timeouts, 5xx) never mark a payment failed; the sweeper (every 2 min) and the poll
  endpoint re-verify. A FAILED payment can still become SUCCESSFUL if the customer retries the same session.
- Posting: Dr processor_clearing (amount + fee) / Cr user wallet (amount) / Cr platform fees (fee).
  Paystack's own cost is booked at settlement reconciliation (Phase 13), not here.
- Fee default mirrors Paystack's published local rate (1.5% + NGN 100, flat waived under NGN 2,500, cap NGN 2,000)
  computed on the amount credited. It is a placeholder for your pricing decision: set FUNDING_FEE_* in settings.
