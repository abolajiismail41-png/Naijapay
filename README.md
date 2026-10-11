# NaijaPay

Modular-monolith payments and bill-payment platform. See `docs/phase0-blueprint.md`.

## Run locally
    make up          # creates .env from .env.example, builds, starts everything
    make migrate && make seed   # then open http://localhost:5173 (see docs/frontend.md for demo logins)
    make test        # unit + API tests in the api container
    make arch        # module-boundary checks (import-linter)
    curl localhost:8000/health/ready

API docs: http://localhost:8000/docs (disabled when ENVIRONMENT=production).

## Auth (Phase 2)
    make up && make migrate
    open http://localhost:8000/docs
In local/test the OTP is readable with `docker compose exec redis redis-cli GET dev:otp:+2348031234567` (never logged).
Integration tests use a separate `<db>_test` database and Redis db 1; they skip if services are unreachable.

## Status
Implemented through Phase 15 at the code level: foundation, authentication, wallet/ledger, wallet funding, bill purchases (airtime, data, electricity, education PINs, TV subscriptions), durable notifications, referrals and promotion wallet rewards, admin operations, fraud review signals, internal ledger reconciliation, frontend polish, and performance/reliability improvements. See `docs/notifications.md`, `docs/referrals-promotions.md`, `docs/admin-operations.md`, and `docs/fraud-reconciliation.md`. This is not yet production-ready: run migrations and the complete test/build suites, configure provider credentials, verify each provider adapter in sandbox, and complete security, reconciliation, monitoring, backup, and compliance reviews before enabling live money movement.


## Admin & operations (Phase 12)

See [`docs/admin-operations.md`](docs/admin-operations.md) for staff permissions, operational overview, user management, audit log, and validation instructions.


## Phase 14 — Frontend polish

Responsive service tiles, accessible route focus and skip navigation, consistent interaction states, narrow-screen table handling, and reduced-motion support are included. See `docs/frontend-polish.md`. Run the frontend type-check, tests, and production build before deployment.

## Phase 15 — Performance & reliability

Customer-facing service and transaction routes are lazy-loaded, frontend API calls have bounded timeouts, query retries use capped backoff without retrying mutations, and backend request completion logs include request IDs and elapsed time. Database connections recycle periodically. See [`docs/performance-reliability.md`](docs/performance-reliability.md). Validate the full test and build suites before deployment.
# Naijapay
