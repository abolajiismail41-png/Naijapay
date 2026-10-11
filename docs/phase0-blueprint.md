# Phase 0 Blueprint: Nigerian Digital Payments Platform

Status legend used throughout: **Designed** only. Nothing here is implemented, tested, or production-ready. Each decision lists the reason and the main alternative.

## 1. Product Requirements

**Users:** retail customers (mobile-first), support, finance, admins.
**Core services:** airtime, data, electricity (prepaid/postpaid), WAEC/NECO PINs, TV subscriptions, extensible via provider plugins.
**Core capabilities:** accounts + OTP, wallet, wallet funding, purchases, history, receipts, notifications, referrals, promotions, support tickets, admin, reconciliation, fraud monitoring.
**Non-functional:** no double charging, no false success, auditable money movement, horizontal API scaling, p95 API latency target (to be set after Phase 16 measurement), graceful provider failure.
**Out of scope now:** bank transfers, virtual accounts, merchant/agent/business wallets, developer API (architecture must allow later).
**Compliance flags (require legal review, not solved by code):** CBN/PSSP or reseller licensing posture, KYC tiers and wallet limits, NDPA 2023 data protection, NDPC registration, tax/VAT on fees, consumer-protection and dispute timelines, record retention, provider agreements (NERC-licensed vendors for electricity, WAEC/NECO reseller approvals).

## 2. System Architecture

```
Clients (React web/PWA, later native)
        |
   CDN / WAF -> Load balancer (TLS)
        |
   FastAPI instances (stateless)  --- Redis (cache, rate limit, locks, Celery broker)
        |                              |
   PostgreSQL (primary) <---- Celery workers (+ beat scheduler)
        |
   External: payment processor (Paystack first), bill providers (via adapters), SMS/email/push
```

- **Modular monolith** with enforced boundaries (import-linter rules in CI). *Why:* one deploy, one transaction scope for money, lower ops cost. *Alternative:* microservices (rejected: distributed transactions on ledger).
- **Sync request path** only for what must be atomic (auth, wallet debit, transaction creation). Provider calls and notifications run via workers. *Alternative:* fully synchronous provider calls (rejected: ties up API workers, poor failure behavior).
- **Celery + Redis broker** with acks-late and idempotent tasks. *Alternatives:* Arq/Dramatiq (lighter), RabbitMQ (stronger delivery guarantees; consider if Redis broker loss becomes a risk). Critical intents are also persisted in a Postgres **outbox** so a lost broker message cannot lose a transaction.

## 3. Backend Architecture

Layering per module: `api (routers) -> service (use cases) -> repository (SQLAlchemy) -> models`. Cross-module calls go through a module's public `interface.py` only, never its tables or repositories.

- **Async:** FastAPI + SQLAlchemy async (asyncpg) + httpx AsyncClient with pooled connections. Celery workers are sync-friendly; share service code via thin adapters.
- **Dependency injection:** FastAPI `Depends` plus a small composition root; no global mutable state.
- **Config:** pydantic-settings, env-only secrets, validated at startup.
- **Errors:** domain exceptions mapped centrally to a stable envelope `{success, data|error{code,message,request_id}}`.
- **Module map:** `auth, users, wallet, ledger, payments, transactions, services (catalogue + pricing), providers, airtime, data, electricity, education, tv, notifications, referrals, promotions, support, admin, audit, fraud, reconciliation, health`.
- **Dependency direction:** product modules (airtime...) -> `transactions` orchestrator -> `wallet/ledger` and `providers`. `ledger` depends on nothing. `audit` and `fraud` are called via events, never block money flow (except hard velocity blocks).

## 4. Frontend Architecture

- **React + TypeScript + Vite**, React Router, TanStack Query (server state), Zustand (small client state), React Hook Form + Zod, generated typed client from OpenAPI.
- **PWA first** (installable, safe-area aware, bottom nav on mobile, sidebar on desktop). *Alternative:* Next.js (SSR helps marketing/SEO; use for the landing site only if needed) or React Native (later, reusing the API).
- **Design system:** tokens (type scale, 4px spacing, one brand color + neutrals + semantic status colors, 2 radii, 2 shadows), components built on Radix primitives for accessibility. Distinct identity to be defined in Phase 1 design brief.
- **3D:** React Three Fiber, lazy-loaded on the landing hero only, tiny glTF with compression, `prefers-reduced-motion` and low-power detection fall back to a static image/SVG.
- **Rules:** no optimistic updates for money; transaction status screens poll/stream server state; virtualized lists; error boundaries; skeletons.
- **Admin:** separate route bundle (or separate app) with its own auth and stricter session policy.

## 5. Database / Entity Model

Conventions: UUIDv7 primary keys (time-sortable, index-friendly), `NUMERIC(20,2)` for NGN amounts (alternatively BIGINT kobo; pick **BIGINT kobo** in code with a Money type, NUMERIC only for rates/percentages), `timestamptz` UTC, soft-delete only for non-financial rows, financial rows are append-only.

Key entities and relations:

- `users`, `user_credentials` (password hash, PIN hash), `user_sessions` (device, refresh token family), `otp_requests`, `roles`, `permissions`, `user_roles`
- `ledger_accounts` (type: USER_WALLET, PLATFORM_REVENUE, PROVIDER_CLEARING, PAYMENT_PROCESSOR_CLEARING, FEES, REFUND_SUSPENSE...), `ledger_journals` (one per business event), `ledger_entries` (journal_id, account_id, direction DEBIT/CREDIT, amount, currency)
- `wallets` (user_id, ledger_account_id, cached `balance`, `version`; derived/verifiable from entries)
- `transactions` (the business record; status, service_type, amount, idempotency_key, user_id), `transaction_events` (state history)
- `payments` (funding attempts with processor reference), `refunds`, `reversals`
- `providers`, `provider_services`, `provider_transactions` (request/response, provider ref, attempts), `provider_health`
- `service_categories`, `services`, `service_plans`, `pricing_rules`, `price_snapshots`
- `airtime_orders`, `data_orders`, `electricity_orders` (meter, token, units), `education_orders` (PIN stored encrypted), `tv_orders` as 1:1 detail tables off `transactions`
- `notifications`, `notification_preferences`, `referrals`, `promotions`, `promotion_redemptions`
- `audit_logs` (append-only), `fraud_events`, `reconciliation_runs`, `reconciliation_records`, `support_tickets`, `support_messages`, `webhook_events` (raw payload, signature result, dedupe key), `outbox_events`, `idempotency_records`

**Key constraints:** unique `(user_id, idempotency_key)` on transactions; unique `(processor, processor_reference)` on payments; unique `(provider, provider_reference)` on provider_transactions; unique `(source, event_id)` on webhook_events; CHECK amount > 0; each journal must balance (enforced by deferred constraint trigger plus service check); wallet balance CHECK >= 0 for user wallets.
**Indexes:** `transactions(user_id, created_at DESC, id)` for keyset pagination, `transactions(status, updated_at)` partial index for non-terminal states, `ledger_entries(account_id, created_at)`, `audit_logs(resource, created_at)`. Partition `ledger_entries`, `audit_logs`, `webhook_events` by month once volume warrants.

## 6. Wallet and Ledger Design

- **Double-entry ledger is the source of truth.** Every money event creates one journal with balanced entries (sum debits = sum credits). Entries are immutable; corrections are new reversing journals.
- **Wallet balance** is a denormalized column updated in the same DB transaction as the entries, with `SELECT ... FOR UPDATE` on the wallet row (or `UPDATE ... WHERE balance >= :amt RETURNING` as an atomic guard). A nightly job recomputes balances from entries and alerts on drift. *Alternative:* compute balance purely from entries (slower reads; use with snapshots later).
- **Purchase flow postings:**
  1. Debit user wallet / credit PROVIDER_CLEARING (hold) when a purchase is accepted.
  2. On provider success: move clearing to settled and book revenue (markup) to PLATFORM_REVENUE.
  3. On provider failure: credit user wallet back (refund journal) linked to the original.
- **Funding:** on verified payment, debit PAYMENT_PROCESSOR_CLEARING / credit user wallet; fees booked separately.
- **Money type:** integer kobo in code, `Decimal` at boundaries, never float.

## 7. Transaction Lifecycle

```
INITIATED -> PENDING (funds held, intent in outbox)
PENDING -> PROCESSING (provider call dispatched)
PROCESSING -> SUCCESSFUL | FAILED | UNKNOWN
UNKNOWN -> (status verification, backoff, bounded) -> SUCCESSFUL | FAILED
FAILED -> REFUNDED (wallet credit journal)
SUCCESSFUL -> REVERSED (rare, finance-approved, with provider confirmation)
```

- Only the state machine in `transactions` may change status; illegal transitions raise. Each transition writes `transaction_events` + audit.
- **Timeouts and 5xx on the purchase call -> UNKNOWN, never FAILED.** Verification uses the provider's query endpoint with our own reference. If a provider has no query API, UNKNOWN is escalated to manual reconciliation and the hold stays.
- **Idempotency:** client sends `Idempotency-Key`; stored with request hash. Same key + same hash returns the original result; same key + different hash returns 422. We also generate our own provider reference per transaction so provider retries are deduplicated on their side where supported.
- **User-facing success** appears only on SUCCESSFUL. PENDING/PROCESSING/UNKNOWN show as "Processing" with an honest message and reference.
- Electricity tokens and education PINs are delivered only on confirmed success, stored encrypted, and shown on the receipt.

## 8. Provider Abstraction

```
BillProvider (health, name, capabilities)
  AirtimeProvider.purchase / verify
  DataProvider.list_plans / purchase / verify
  ElectricityProvider.validate_meter / purchase / verify
  EducationProvider.purchase / verify
  TVProvider.validate_smartcard / list_bouquets / purchase / verify
```

- Adapters translate to a normalized result: `ACCEPTED | SUCCESS | FAILED(reason, retryable) | UNKNOWN`.
- A **registry + routing table** (DB-driven) picks a provider per service with priority and weights; failover only occurs when the first attempt is definitively FAILED, never on UNKNOWN (to avoid double delivery).
- **Resilience:** per-provider timeouts, retry with jittered exponential backoff only for safe/idempotent calls (validation, verify), circuit breaker state in Redis, health checks stored in `provider_health`.
- **Sandbox adapter** implements the same interface with configurable scripted outcomes (success, failure, timeout-then-success, duplicate webhook) for tests. It is clearly flagged and disabled in production config.
- Provider selection is *alternative-friendly*: Paystack for funding first; bill providers chosen in Phase 5 based on API quality, query endpoints, and approval timelines (to be confirmed, not assumed).

## 9. Security Architecture

- **Transport/headers:** HTTPS only, HSTS, CSP, strict CORS allowlist, request size limits.
- **Secrets:** env/secret manager; app-level encryption (envelope, key IDs for rotation) for PINs-to-deliver, tokens, KYC fields.
- **AuthZ:** RBAC with explicit permissions (`refund.approve`, `ledger.adjust`...), enforced by server-side dependencies; dangerous finance actions need a **maker-checker** (two distinct staff). ADMIN is not implicitly FINANCE.
- **Abuse:** Redis rate limits per IP/user/device/endpoint, progressive lockouts, OTP attempt caps, velocity rules.
- **Data:** parameterized queries via ORM, output escaping on frontend, no PII or secrets in logs (log filters + tests), SSRF-safe outbound client (allowlisted hosts).
- **Webhooks:** raw-body HMAC verification (constant-time), timestamp/replay window where supported, dedupe via `webhook_events`, then **re-verify with the provider's API** before crediting. Amount/currency/reference/user checked against our own payment row.
- **Supply chain:** pinned dependencies, SCA and SAST in CI, container scanning.
- **Threat model** (STRIDE) to be maintained in `docs/security/`.

## 10. Authentication Architecture

- Phone number (primary) + email, password hashed with **Argon2id**. OTP via SMS with hashed storage, expiry, attempt and resend limits.
- Short-lived JWT access tokens (about 10-15 min), opaque rotating refresh tokens stored hashed with token-family reuse detection (reuse revokes the family). Sessions/devices listable and revocable.
- **Transaction PIN** (separate from password, Argon2id, attempt-limited) required for purchases and sensitive changes; step-up for high-value or new-device actions.
- Admin: separate login policy, TOTP 2FA (architecture now, enforced for staff), shorter sessions, optional IP allowlist.
- *Alternative:* delegated provider (Auth0/Cognito/Keycloak) reduces build time; chosen against because of OTP/PIN customization and cost at scale, revisit if team is small.

## 11. Admin Architecture

- Same backend, `/api/v1/admin/*`, separate router set, permission-gated per endpoint, rate-limited, every action audited with before/after state.
- Sections: dashboard (operational metrics split from financial), users, wallets, transactions (search, status, force-verify), provider status/routing, refunds (maker-checker), reconciliation, fraud queue, support tickets, audit viewer, system health.
- Read-heavy analytics served from read replica / materialized views later; never run heavy reports on the primary.

## 12. Notification Architecture

- `NotificationService` -> templates -> channel adapters (SMS, email, push) -> delivery log, all triggered by **outbox events** after the transaction commits.
- Workers retry with backoff; failures never affect transaction state. Per-user preferences; security events are non-optional.
- Channel providers are pluggable (SMS gateway and email vendor to be chosen; local sender-ID registration requirements apply).

## 13. Reconciliation Architecture

- Three-way comparison: internal transactions vs payment-processor records (API/settlement files) vs bill-provider records.
- Scheduled runs (daily, plus intraday for pending) produce `reconciliation_records` classified as: MATCHED, MISSING_INTERNAL, MISSING_EXTERNAL, AMOUNT_MISMATCH, STATUS_MISMATCH, DUPLICATE, STUCK_PENDING.
- Discrepancies create finance tasks; resolutions are explicit actions (credit, refund, mark matched) that post ledger journals, never silent edits.
- Plus internal integrity checks: journals balanced, wallet balance = sum of entries, no orphan holds.

## 14. Deployment Architecture

- Docker images (multi-stage, non-root), `docker-compose` for local (api, worker, beat, postgres, redis, frontend).
- Production target: managed Postgres with PITR and automated backups, managed Redis, 2+ API instances behind a load balancer, separate worker pools, migrations as a gated release step, blue/green or rolling deploys. Cloud/region choice (Nigerian latency vs. data-residency considerations) is open and needs a decision before Phase 18.
- Backups: tested restores, documented RPO/RTO targets (to be set by the business).

## 15. Scalability Strategy

Stateless API, pooled DB connections (PgBouncer when instances grow), keyset pagination, cached catalogue, queue-based provider work, row-level locks scoped to a single wallet (low contention since each user has one wallet). Later: read replicas, partitioning, Redis cluster, dedicated queues per provider, extraction of `providers`/`notifications` first if needed. Hot spots to watch: platform-level ledger accounts (revenue/clearing) can become lock contention points; mitigate with sub-accounts sharded per time/provider and periodic aggregation.

## 16. Performance Strategy

Define SLOs first, then measure: Prometheus metrics + OpenTelemetry traces, DB slow-query logging with `pg_stat_statements`, k6/Locust load tests from Phase 16, frontend Lighthouse/Web Vitals budgets (3D lazy-loaded, bundle limits in CI). No tuning without a measurement.

## 17. Testing Strategy

- **Unit:** money type, ledger balancing, state machine, pricing, adapters (against recorded fixtures), idempotency.
- **Integration:** real PostgreSQL and Redis via testcontainers; provider contract tests against sandbox; webhook signature tests.
- **Concurrency:** parallel debits on one balance, duplicate idempotency keys, duplicate and simultaneous webhooks, timeout-then-success provider simulation.
- **Security:** authz matrix tests (every endpoint x role), token reuse/replay, rate-limit, injection fuzzing.
- **E2E:** Playwright for core purchase journey. Property-based tests (Hypothesis) for ledger invariants. CI gates on all of the above.

## 18. Recommended Directory Structure

```
repo/
  backend/
    app/
      core/ (config, db, redis, security, errors, logging, money)
      modules/
        auth/ users/ wallet/ ledger/ payments/ transactions/
        services/ providers/ airtime/ data/ electricity/ education/ tv/
        notifications/ referrals/ promotions/ support/ admin/
        audit/ fraud/ reconciliation/ health/
        (each: api.py, schemas.py, service.py, repository.py, models.py, interface.py)
      workers/ (celery app, tasks, beat schedule)
      main.py
    migrations/ (alembic)
    tests/ (unit, integration, concurrency, security, api)
    pyproject.toml, Dockerfile
  frontend/
    src/ (app, routes, features, components, design-system, lib/api, 3d, hooks)
  infra/ (docker, compose, deploy, monitoring)
  docs/ (architecture, database, api, security, runbooks, reconciliation)
  docker-compose.yml, Makefile, .env.example, README.md
```

## 19. API Architecture

- Versioned `/api/v1/...` per module; OpenAPI as the contract; typed frontend client generated from it.
- Envelope: `{success, data, message}` / `{success:false, error:{code, message, request_id}}`.
- `Idempotency-Key` header mandatory on money-moving POSTs. `X-Request-ID` generated or propagated and returned.
- Keyset pagination (`cursor`, `limit`), consistent filtering, rate-limit headers, webhook endpoints separate under `/api/v1/webhooks/{source}` with raw-body handling.
- Purchases return **202-style semantics**: transaction with current status and reference; clients poll `GET /transactions/{id}` (SSE optional later).

## 20. Development Roadmap

| Phase | Deliverable | Exit gate |
|---|---|---|
| 1 | Repo, Docker, config, logging, health, CI, design brief | `make up` works from clean machine |
| 2 | Auth, sessions, OTP, PIN, RBAC base | authz and token tests pass |
| 3 | Wallet + ledger + Money type | ledger invariant and concurrency tests pass |
| 4 | Paystack funding + webhooks | duplicate/forged/mismatch webhook tests pass |
| 5-9 | Airtime, data, electricity, WAEC/NECO, TV | state machine incl. UNKNOWN path tested per service |
| 10-11 | Notifications, referrals, promotions | outbox delivery tests |
| 12-13 | Admin, fraud, reconciliation | maker-checker and recon tests |
| 14-17 | Frontend polish, full tests, load tests, hardening | SLOs met, pen-test findings triaged |
| 18-20 | Deployment, monitoring, backups, release | restore drill, runbooks, legal sign-off |

## Open Decisions Needed From You

1. Funding processor: Paystack first, or Flutterwave?
2. Bill-provider aggregator(s) you have or plan to apply for (determines query/verify capabilities).
3. Licensing/KYC posture and wallet limits (needs a Nigerian fintech lawyer).
4. Cloud/hosting region and budget.
5. Team size and whether native mobile is planned (affects PWA vs React Native).
6. Brand direction (name, colors, tone) for the design language.
7. Is the transaction PIN 4 or 6 digits, and is SMS OTP mandatory at sign-up?

## Status Summary

Designed: everything above. Implemented: none. Tested: none. Requires external credentials: payment processor, bill providers, SMS/email. Requires provider approval: bill providers, WAEC/NECO reselling. Requires production infrastructure: managed Postgres/Redis, secrets manager. Requires legal/compliance review: licensing, KYC, NDPA, tax, consumer protection.
