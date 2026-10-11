# Phase 10 — Notifications

## Scope

Notifications are durable business events, not fire-and-forget side effects. The `notifications` inbox row and any `notification_deliveries` are created in the same PostgreSQL transaction as the financial status change. The unique `event_key` prevents duplicate inbox events when a provider callback or worker is replayed.

## Channels

- **In-app:** implemented through the authenticated inbox API and the responsive frontend.
- **Email:** SMTP transport; enabled only when `SMTP_HOST` and `SMTP_FROM_EMAIL` are configured. SMTP acceptance is recorded as `SENT`; it is not proof that the recipient read the email.
- **SMS:** Termii adapter; enabled only when `TERMII_API_KEY` and `TERMII_SENDER_ID` are configured. Provider acceptance is recorded, not handset delivery confirmation.
- **Push:** preference field reserved, but device registration and a push transport are not implemented in this phase. The UI explicitly says this channel is not enabled; the system must not claim push delivery.

External channels are opt-in per user. Transport failures do not roll back funding or purchase settlement. Delivery attempts use a bounded exponential backoff, capped at eight attempts by default. Permanent provider rejection becomes `DEAD`; missing configuration becomes `BLOCKED`. `SENDING` rows older than five minutes are recovered by the next sweep so a worker crash does not strand work.

## API

- `GET /api/v1/notifications?limit=20&cursor=<uuid>` — keyset-paginated inbox and unread count.
- `POST /api/v1/notifications/read` — mark up to 100 owned notification IDs as read.
- `POST /api/v1/notifications/read-all` — mark the current user's inbox read.
- `GET /api/v1/notifications/preferences` — read channel preferences.
- `PATCH /api/v1/notifications/preferences` — update email/SMS preferences and email destination.

Every route requires authentication. Notification reads and updates are scoped to the authenticated user.

## Event integration

- Purchase state transitions to `SUCCESSFUL`, `REFUNDED`, and `UNKNOWN` create a durable notification.
- Verified wallet funding creates a `WALLET` notification only after the payment processor verification and ledger credit succeed.
- A notification transport is never allowed to decide or mutate financial state.

## Configuration

Optional settings are in `.env.example`: `SMTP_*`, `TERMII_*`, and `NOTIFICATION_MAX_ATTEMPTS`. Leave them blank until the respective provider account and sender identity are configured. Never place live secrets in source control.

## Operations and limitations

The Celery Beat task `notifications.deliver_due` runs every 15 seconds. Monitor delivery rows by `status`, `attempts`, `last_error_code`, and `next_attempt_at`. Add dashboards/alerts for growing `PENDING`, `BLOCKED`, or `DEAD` counts before production launch. Configure SPF/DKIM/DMARC for email and verify Termii sender approval, destination formatting, message templates, and delivery receipts in a staging account. Push notifications need a separately reviewed device-token registration and provider implementation.
