# Ledger and wallet design (Phase 3)

- Every money event is one **journal** with balanced **entries** (debits = credits, in integer kobo).
  `reference` is unique and is the idempotency key. Same reference + same payload replays safely;
  same reference + different payload is rejected (409).
- Postgres enforces: entries and journals are append-only (triggers), journals balance at COMMIT
  (deferred constraint trigger), amounts are positive, wallet balance >= 0, a journal can be reversed once.
- `wallets.balance_kobo` is a cache of the ledger, changed in the same transaction under a row lock
  (`SELECT ... FOR UPDATE` + guarded `UPDATE ... WHERE balance + delta >= 0`). `verify_integrity` compares
  it with the ledger; `trial_balance_diff` must always be 0.
- Postings: funding = Dr processor_clearing / Cr wallet. Purchase hold = Dr wallet / Cr provider_clearing.
  Reversal/refund = the mirror journal, linked through `reverses_journal_id`.
- `WalletService` never commits; the use case that owns the transaction does. There is no public
  endpoint that moves money in Phase 3: funding arrives in Phase 4, purchases in Phase 5+.
- Accounts: user wallets are LIABILITY accounts (`wallet:<user_id>`); system accounts are seeded by migration 0002.
