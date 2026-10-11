# Phase 15 — Performance & Reliability

Phase 15 adds resilience and diagnostics around the existing payment flows without changing ledger semantics, transaction states, or provider retry policy.

## Frontend

- Customer service, activity, funding, notification, rewards, and transaction-detail routes are lazy-loaded. Admin routes remain split from the customer bundle.
- API calls have a 20-second client timeout and continue to support caller-provided `AbortSignal` cancellation.
- React Query uses a bounded cache lifetime, refreshes stale data on focus/reconnect, applies capped exponential retry delays for transient failures, and never retries mutations automatically. This avoids accidental duplicate financial writes.

## Backend

- Request middleware emits structured completion logs with method, path, status code, elapsed milliseconds, and request ID. Query strings and request bodies are deliberately excluded.
- Database connections use `pool_pre_ping` and a 30-minute recycle interval to reduce stale connection failures.
- Existing `/health/live` remains a liveness check; `/health/ready` checks PostgreSQL and Redis with bounded timeouts and returns HTTP 503 when either dependency is unavailable.
- Existing HTTP connection pooling, database pool limits, idempotency controls, Celery late acknowledgements, and single-flight token refresh remain in place.

## Operational guidance

1. Alert on sustained 5xx responses, elevated request latency, readiness failures, Celery queue age, database pool exhaustion, and provider timeout/error rates.
2. Treat client timeouts on payment operations as **unknown outcomes**, not proof of failure. Clients should query transaction status and use the same idempotency key when retrying a supported operation; never create a new purchase simply because a request timed out.
3. Do not enable automatic retries for wallet mutations or provider purchase POSTs unless the operation has an explicit idempotency guarantee.
4. Tune pool sizes and HTTP connection limits from measured production concurrency and database capacity rather than increasing them blindly.
5. Add load tests against a staging environment with sandbox providers before choosing SLO thresholds.

## Validation

Run `docker compose run --rm api pytest -q`, `docker compose run --rm frontend npm run typecheck`, `docker compose run --rm frontend npm test`, and `docker compose run --rm frontend npm run build`. Also exercise readiness while PostgreSQL or Redis is stopped and confirm a slow client request times out cleanly.

This phase adds observability and client-side resilience, not a complete monitoring platform or a guarantee of high availability. Metrics export, alert routing, load testing, deployment replicas, and recovery drills remain operational follow-up work.
