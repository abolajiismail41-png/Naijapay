# Phase 13 — Fraud monitoring and reconciliation

## Fraud monitoring

`fraud.scan_recent` runs every five minutes and evaluates a bounded recent transaction window. The initial rules flag:

- high-value transactions (`FRAUD_HIGH_VALUE_KOBO`, default ₦50,000);
- high-value transactions from users without a verified phone (`FRAUD_UNVERIFIED_VALUE_KOBO`, default ₦20,000);
- user transaction velocity above a configurable threshold (`FRAUD_VELOCITY_WINDOW_MIN`, `FRAUD_VELOCITY_COUNT`).

Cases are deduplicated by `(transaction_id, rule_code)` and appear in `/api/v1/admin/fraud`. Staff with `fraud.review` can mark a case reviewing, cleared, or confirmed and must provide a note. Changes are audit logged. **Signals are review-only**: this phase does not automatically suspend accounts, block purchases, or change financial records. The initial rules are conservative starting points and require calibration against actual traffic and false-positive rates.

## Reconciliation

`POST /api/v1/admin/reconciliation/run` runs read-only internal checks. `GET /api/v1/admin/reconciliation` lists runs and `GET /api/v1/admin/reconciliation/{run_id}/records` lists discrepancy records. Celery also runs the same internal check daily.

Checks include:

- total ledger debits equal total ledger credits;
- each sampled journal is balanced;
- successful transactions have a settlement journal reference and that reference exists;
- refunded transactions have a refund journal reference;
- long-running pending/processing/unknown transactions are surfaced for review.

Discrepancy evidence is persisted in `reconciliation_runs` and `reconciliation_records`. Runs do not repair balances, issue refunds, or resolve transactions automatically.

## Important scope boundary

This is **internal consistency reconciliation**, not full external settlement reconciliation. Bank/Paystack settlement reports and provider transaction exports are not yet ingested or matched. External missing/duplicate/amount-mismatch classifications require those feeds and a controlled matching process. No automated financial adjustment is performed by this phase.

## Endpoints

- `GET /api/v1/admin/fraud?status=OPEN&severity=HIGH`
- `PATCH /api/v1/admin/fraud/{case_id}` with `{ "status": "REVIEWING|CLEARED|CONFIRMED", "note": "..." }`
- `POST /api/v1/admin/reconciliation/run`
- `GET /api/v1/admin/reconciliation?status=ISSUES`
- `GET /api/v1/admin/reconciliation/{run_id}/records?limit=100`

Migration: `0011`, after `0010`. Fraud review requires `fraud.review`; reconciliation requires `reconciliation.run`.
