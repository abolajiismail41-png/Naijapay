# Frontend

React 18 + TypeScript + Vite, mobile-first, no UI framework. Everything customer-facing talks to the real backend; nothing is mocked.

## Run it locally
```
make up            # api, worker, postgres, redis, frontend
make migrate
make seed          # local only: admin + demo customer + sandbox catalogue + NGN 50,000 demo wallet
open http://localhost:5173
```
| Who | Phone | Password | PIN |
|---|---|---|---|
| Customer | 08000000002 | `Demo-pass-1!` | 4821 |
| Admin (SUPER_ADMIN) | 08000000001 | `Admin-pass-1!` | 4821 |

Sign-up OTPs are never logged: read one with `docker compose exec redis redis-cli GET dev:otp:+2348031234567`.
Wallet funding uses the sandbox processor locally: the checkout step shows a "Simulate successful payment" button
(`VITE_DEV_TOOLS=true`, backend `POST /api/v1/dev/sandbox/complete-funding`, mounted only when `ENVIRONMENT=local` and
`PAYMENT_PROCESSOR=sandbox`). With a Paystack test key set instead, the real Paystack checkout opens.
Vite proxies `/api` to the backend (`API_PROXY_TARGET`), so the browser only ever uses its own origin: no CORS in dev.
Production: `Dockerfile.prod` (nginx serves the build, proxies `/api`, sets a strict CSP and security headers).

## What is connected
Sign-up with OTP, login, password reset, sessions list/revoke, transaction PIN set/change, wallet balance, funding (quote, Paystack redirect,
status polling), airtime, data, electricity (meter verification, fee shown, token reveal), exam PINs (quantity, PIN reveal), purchase history,
wallet movements, receipts (print / share), and an admin area: profit dashboard + ledger checks, pricing calculator + rules + provider costs,
catalogue listing for data / electricity / exam products, transaction lookup with manual resolution. 45 distinct API calls; each was checked
against the backend's route table.

## Safety decisions (money UI)
- **Success is never invented.** After a purchase the app navigates to the receipt, which shows the server's status and message and keeps
  polling while it is open (Processing / Confirming / Successful / Failed / Refunded). Unknown outcomes say "do not retry".
- **One idempotency key per attempt**, kept across network failures, so a retry cannot charge twice; a new key is made only after a definite rejection.
- **PIN -> single-use token.** The PIN is exchanged at `/auth/pin/verify`; the purchase request carries only the 2-minute token.
- **Price confirmation.** Every purchase sends the price the customer saw; if it changed the server refuses and the app shows the new price.
- **Tokens and PINs** are fetched only on demand from their audited endpoints, hidden again after a minute, never cached in lists.
- **Funding** credits nothing client-side: the result page only reports what the server verified with Paystack.
- **Token storage.** The access token lives in memory only; the refresh token is in `localStorage` so mobile sessions survive restarts.
  That is an XSS trade-off: the CSP blocks inline/third-party scripts, but moving the refresh token to an HttpOnly cookie (needs a small
  backend change) is the stronger design and is on the hardening list.
- **Refresh is single-flight** (and serialised across tabs with the Web Locks API) because rotation + reuse detection would sign the user out
  if two refreshes raced.
- Money is integer kobo end to end; amounts typed by users are parsed with string arithmetic, never floats.
- Customer screens receive no cost, markup, margin or profit fields because the backend never sends them; admin screens are lazy-loaded
  and every action is enforced server-side (the UI only hides what a role cannot use).

## Design
Warm paper background, ink text, one green accent, two radii, one shadow, tabular numerals for money, hairline borders; wallet is a flat
dark card, services are list rows (not icon tiles). Light and dark follow the OS. Bottom navigation on phones, a left rail on desktop, safe-area
insets, 48px touch targets, visible focus, reduced-motion respected, `aria-live` on prices and statuses. The landing hero is a small three.js coin
stack, lazy-loaded only when the device can afford it (no reduced motion, no save-data, enough CPU/memory, WebGL present); otherwise an SVG.
The brand name/colours are placeholders in `src/config.ts` and `src/styles/tokens.css`.

## Not built (backend does not exist yet)
Notifications, referrals, promotions, support tickets, TV subscriptions, in-app receipts by SMS/email. The UI does not pretend otherwise.

## Verification status
Checked here: all pure logic (money, phone, API client including parallel-401 single refresh, error mapping, refresh-token handling) executes and passes;
every frontend API call exists in the backend; no syntax errors across the 46 TS/TSX files. NOT checked here (no network to install packages):
`npm install`, the full type-check (`npm run typecheck`), the production build, vitest, and any browser run. Expect a few small type
fixes on first compile. Still to do: component tests, Playwright journeys (sign-up -> fund -> buy -> receipt), accessibility audit (axe),
Lighthouse budgets, a real-device pass, and an HttpOnly-cookie refresh flow.
