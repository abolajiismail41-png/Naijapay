# TV subscriptions (Phase 9)

## Flow

1. The customer chooses an enabled operator.
2. `POST /api/v1/tv/validate` validates the smartcard/IUC number with the configured bill provider. The validation record is short-lived in Redis and bound to the authenticated user.
3. The customer chooses an enabled package and requests a quote. The backend uses the current provider cost and the `TV` pricing rule.
4. The customer confirms the exact price and authenticates with their transaction PIN.
5. The backend creates the transaction, immutable pricing snapshot, TV order and wallet hold in one database transaction, then dispatches the provider call.
6. A confirmed provider success settles the hold. A definitive failure refunds it. Timeout, invalid response and other ambiguous outcomes remain `UNKNOWN` and are verified through the existing transaction recovery path.

## Provider catalogue setup

TV products are deliberately **not seeded with invented live IDs**. Use `POST /api/v1/admin/tv/products` with a finance/pricing-authorized staff session to add each package. Provide:

- `operator_code`: stable internal code such as `GOTV`;
- `operator_name`: customer-facing name;
- `provider_operator_id`: the Inlomax service ID accepted by smartcard validation;
- `provider_service_id`: the selected bouquet/package service ID accepted by purchase;
- `name`: customer-facing package name;
- `cost_kobo`: verified provider cost in kobo.

New products start unlisted. Review the provider ID mapping and price, then enable a product with `PATCH /api/v1/admin/tv/products/{id}` and `{"listed": true}`. Listing is rejected if the provider cost or sell price is unavailable. Update the default TV markup under `/api/v1/admin/pricing` before enabling products in a live environment.

Inlomax documents `POST /validatecable` using `serviceID` and `iucNum`, and `POST /subcable` using `serviceID`, `iucNum`, and `request-id`. Its service catalogue also exposes `cablePlans`. Since the validation operator ID and package ID are separate concepts, configure and verify both IDs against the provider account/sandbox before enabling any product. Do not copy sample IDs into production without verification.

## API

- `GET /api/v1/tv/operators`
- `GET /api/v1/tv/plans?operator_code=GOTV`
- `POST /api/v1/tv/validate`
- `POST /api/v1/tv/quote`
- `POST /api/v1/tv` (requires `Idempotency-Key` and `X-PIN-Token`)
- `GET /api/v1/admin/tv/products`
- `POST /api/v1/admin/tv/products`
- `PATCH /api/v1/admin/tv/products/{id}`

## Safety notes

- Purchase calls are never blindly retried by the Inlomax adapter.
- Provider success is not inferred from frontend state.
- Validation details are short-lived and user-bound; the raw smartcard number is masked in customer-facing responses.
- The provider adapter maps unknown/unparseable outcomes to `UNKNOWN`, not `FAILED`.
- The production catalogue is empty until an authorized operator configures and verifies real products.
