# Phase 12 — Admin & Operations

This phase extends the existing staff-only `/api/v1/admin/*` area with operational overview metrics, customer search/detail, controlled account suspension/reactivation, and a read-only audit viewer. It does not create a separate financial ledger or allow direct balance edits.

## API

- `GET /api/v1/admin/overview` — operational counts (users and transaction statuses); deliberately excludes profit and monetary totals.
- `GET /api/v1/admin/users?q=&status=&cursor=&limit=` — keyset-paginated user search by name, phone, or UUID.
- `GET /api/v1/admin/users/{user_id}` — account status, wallet snapshot, active-session count, and transaction counts.
- `PATCH /api/v1/admin/users/{user_id}/status` — suspend/reactivate a customer with a required reason; staff status changes are restricted to SUPER_ADMIN.
- `GET /api/v1/admin/audit?action=&resource_type=&cursor=&limit=` — read-only audit events for staff with `audit.read`.

All routes require a valid authenticated session and server-side permission checks. UI checks are only for navigation; they are not an authorization boundary. The user status endpoint never changes wallet balances, creates ledger journals, edits transaction state, or assigns roles.

## Security behavior

- Suspending a user revokes active refresh sessions in the database and marks each session family revoked in Redis so existing access tokens are rejected immediately.
- Reactivating a user does not revive revoked sessions; the customer must sign in again.
- Staff accounts cannot be suspended/reactivated by ordinary ADMIN accounts; SUPER_ADMIN is required.
- A staff member cannot change their own account status through this endpoint.
- Each status change records the actor, request IP/session, prior and new status, reason, and number of session families revoked.
- Audit responses are read-only and do not offer mutation endpoints.
- Operational overview shows counts, not profit or money totals; financial reporting stays behind `finance.profit.read`.

## Limitations and next steps

- This phase does not implement staff role assignment, manual wallet adjustment, refund approval, provider routing, or maker-checker workflows. Dangerous finance actions must remain separate permission-gated flows.
- Provider health/routing and support ticket management remain future operational modules. Fraud review and internal reconciliation are available in Phase 13; external provider/bank statement matching remains future work.
- Pagination is cursor-based; use narrower filters for very large user directories.
- Admin TOTP enforcement and IP allowlisting remain deployment/security follow-ups; do not treat this phase as a complete production security review.

## Validation

Run the project integration suite against PostgreSQL and Redis, then type-check/build the frontend:

```bash
docker compose run --rm api pytest -q
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm test
```
