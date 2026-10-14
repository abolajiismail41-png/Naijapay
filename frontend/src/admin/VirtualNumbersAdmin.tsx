import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import {
  Banner,
  Button,
  Field,
  PageHead,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { api, friendly, SLOW_REQUEST_TIMEOUT_MS } from "../lib/api";
import { formatKobo } from "../lib/money";

type ProviderStatus = {
  enabled: boolean;
  configured: boolean;
  api_version: string;
  currency: string;
  ngn_rate_configured: boolean;
  esim_enabled: boolean;
};

type Pricing = {
  markup_percent: string;
  fixed_fee_kobo: number;
  min_price_kobo: number;
  max_price_kobo: number;
  enabled: boolean;
};

type CatalogueCountry = { id: number; name: string };
type CatalogueService = { id: number; name: string };

type CataloguePrice = {
  application_id: number;
  service_name: string;
  provider_cost_kobo: number;
  price_kobo: number;
  inventory: number | null;
  available: boolean | null;
};

type Catalogue = {
  countries: CatalogueCountry[];
  services: CatalogueService[];
  fetched_at: string;
  prices: CataloguePrice[];
  // Diagnostics returned by the backend when a country is selected.
  price_diagnostics?: Record<string, unknown>;
};

type Report = {
  orders: number;
  sales_kobo: number;
  estimated_supplier_cost_kobo: number;
  estimated_margin_kobo: number;
  note: string;
};

type Order = {
  id: string;
  reference: string;
  status: string;
  transaction_status?: string;
  country_name: string;
  service_name: string;
  phone_number?: string | null;
  price_kobo: number;
  provider_cost_kobo?: number;
  margin_kobo?: number;
  provider_request_id?: number | null;
  failure_reason?: string | null;
  user_id: string;
  created_at: string;
};

type ResolvePayload = {
  id: string;
  body: {
    outcome: "SUCCESS" | "FAILED";
    note: string;
    provider_request_id?: number;
    phone_number?: string;
    provider_cost_kobo?: number;
  };
};

const MAX_SAFE_AMOUNT = Number.MAX_SAFE_INTEGER;
const MAX_MARKUP = 500;

// A PENDING order whose transaction is still PROCESSING is only treated as
// stuck once it is older than this, so an in-flight purchase is never
// resolved underneath the request that is still running.
const STUCK_AFTER_MS = 10 * 60 * 1000;

const ORDER_STATUSES = [
  "PENDING",
  "ACTIVE",
  "SMS_RECEIVED",
  "UNKNOWN",
  "FAILED",
  "CANCELLING",
  "CANCELLED",
];

function parseNonNegativeInteger(value: string): number | null {
  const normalized = value.trim();

  if (!/^\d+$/.test(normalized)) return null;

  const parsed = Number(normalized);

  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}

function parsePositiveInteger(value: string): number | null {
  const parsed = parseNonNegativeInteger(value);

  return parsed !== null && parsed > 0 ? parsed : null;
}

function isStaffRole(role?: string | null): boolean {
  return ["ADMIN", "SUPER_ADMIN", "FINANCE"].includes(role ?? "");
}

function validKobo(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= MAX_SAFE_AMOUNT
  );
}

/**
 * Orders an administrator may reconcile. The backend only accepts a
 * resolution while the transaction is PROCESSING or UNKNOWN.
 */
function isReconcilable(order: Order): boolean {
  const txn = order.transaction_status;

  if (txn === undefined) return order.status === "UNKNOWN";

  if (txn !== "PROCESSING" && txn !== "UNKNOWN") return false;

  if (order.status === "UNKNOWN") return true;

  if (order.status === "PENDING") {
    const created = Date.parse(order.created_at);

    return (
      Number.isFinite(created) && Date.now() - created > STUCK_AFTER_MS
    );
  }

  return false;
}

export default function VirtualNumbersAdmin() {
  const { me } = useAuth();
  const qc = useQueryClient();

  const role = me?.role;
  const canManageProvider = role === "ADMIN" || role === "SUPER_ADMIN";
  const canManagePricing = role === "FINANCE" || role === "SUPER_ADMIN";
  const canSeeCosts = canManagePricing;
  const canResolve = canManagePricing;
  const canViewOrders = isStaffRole(role);

  const [markup, setMarkup] = useState("15");
  const [fee, setFee] = useState("0");
  const [minPrice, setMinPrice] = useState("100");
  const [maxPrice, setMaxPrice] = useState("5000000");
  const [enabled, setEnabled] = useState(true);

  const [catalogueCountry, setCatalogueCountry] = useState("");
  const [catalogueRequested, setCatalogueRequested] = useState(false);
  const [catalogueRefresh, setCatalogueRefresh] = useState(0);

  const [searchOrders, setSearchOrders] = useState("");
  const [orderStatus, setOrderStatus] = useState("");

  // The catalogue is keyed by country, so a slow response for a previously
  // selected country can never overwrite the data for the current one.
  const selectedCountryId =
    catalogueCountry === "" ? undefined : Number(catalogueCountry);

  // Country ID 0 is a valid SMS-Man country, so only negative or
  // non-integer values are rejected.
  const validCountrySelection =
    selectedCountryId === undefined ||
    (Number.isSafeInteger(selectedCountryId) && selectedCountryId >= 0);

  const catalogueQuery = useQuery({
    queryKey: [
      "admin-vnumber-catalogue",
      selectedCountryId ?? null,
      catalogueRefresh,
    ],
    queryFn: () =>
      api.get<Catalogue>(
        "/api/v1/admin/virtual-numbers/catalogue",
        selectedCountryId === undefined
          ? undefined
          : { country_id: selectedCountryId },
        // Provider-backed lookup: allow far longer than the 20s default.
        { timeoutMs: SLOW_REQUEST_TIMEOUT_MS },
      ),
    enabled:
      canManageProvider && catalogueRequested && validCountrySelection,
    retry: false,
    staleTime: 0,
    // Keep showing the previous result while a new country loads, so the
    // country dropdown does not empty out and reset itself.
    placeholderData: (previous) => previous,
  });

  const catalogue = catalogueQuery.data;

  const refreshCatalogue = () => {
    if (!validCountrySelection) return;
    setCatalogueRequested(true);
    setCatalogueRefresh((value) => value + 1);
  };

  const selectCatalogueCountry = (value: string) => {
    setCatalogueCountry(value);
    setCatalogueRequested(true);
  };

  const report = useQuery({
    queryKey: ["admin-vnumber-report"],
    queryFn: () => api.get<Report>("/api/v1/admin/virtual-numbers/report"),
    retry: false,
    enabled: canSeeCosts,
  });

  const pricing = useQuery({
    queryKey: ["admin-vnumber-pricing"],
    queryFn: () => api.get<Pricing>("/api/v1/admin/virtual-numbers/pricing"),
    retry: false,
    enabled: canManagePricing,
  });

  useEffect(() => {
    if (!pricing.data) return;

    setMarkup(pricing.data.markup_percent);
    setFee(String(pricing.data.fixed_fee_kobo));
    setMinPrice(String(pricing.data.min_price_kobo));
    setMaxPrice(String(pricing.data.max_price_kobo));
    setEnabled(pricing.data.enabled);
  }, [pricing.data]);

  const status = useQuery({
    queryKey: ["admin-vnumber-status"],
    queryFn: () =>
      api.get<ProviderStatus>("/api/v1/admin/virtual-numbers/provider-status"),
    retry: false,
    enabled: canManageProvider,
  });

  const normalizedSearch = searchOrders.trim();

  const orders = useQuery({
    queryKey: ["admin-vnumber-orders", normalizedSearch, orderStatus],
    queryFn: () =>
      api.get<Order[]>("/api/v1/admin/virtual-numbers/orders", {
        search: normalizedSearch || undefined,
        status: orderStatus || undefined,
      }),
    retry: false,
    enabled: canViewOrders,
  });

  const resolveOrder = useMutation({
    mutationFn: (payload: ResolvePayload) =>
      api.post<Order>(
        `/api/v1/admin/virtual-numbers/orders/${encodeURIComponent(payload.id)}/resolve`,
        payload.body,
      ),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["admin-vnumber-orders"] }),
        qc.invalidateQueries({ queryKey: ["admin-vnumber-report"] }),
      ]);
    },
  });

  const markupValue = Number(markup);
  const feeValue = parseNonNegativeInteger(fee);
  const minPriceValue = parsePositiveInteger(minPrice);
  const maxPriceValue = parsePositiveInteger(maxPrice);

  const pricingInputValid =
    markup.trim() !== "" &&
    Number.isFinite(markupValue) &&
    markupValue >= 0 &&
    markupValue <= MAX_MARKUP &&
    feeValue !== null &&
    minPriceValue !== null &&
    maxPriceValue !== null &&
    maxPriceValue >= minPriceValue;

  const updatePricing = useMutation({
    mutationFn: () =>
      api.patch<Pricing>("/api/v1/admin/virtual-numbers/pricing", {
        markup_percent: markup.trim(),
        fixed_fee_kobo: feeValue,
        min_price_kobo: minPriceValue,
        max_price_kobo: maxPriceValue,
        enabled,
      }),
    onSuccess: async (value) => {
      setMarkup(value.markup_percent);
      setFee(String(value.fixed_fee_kobo));
      setMinPrice(String(value.min_price_kobo));
      setMaxPrice(String(value.max_price_kobo));
      setEnabled(value.enabled);

      await Promise.all([
        qc.invalidateQueries({ queryKey: ["admin-vnumber-pricing"] }),
        qc.invalidateQueries({ queryKey: ["admin-vnumber-report"] }),
        qc.invalidateQueries({ queryKey: ["admin-vnumber-catalogue"] }),
      ]);
    },
  });

  const handleSavePricing = () => {
    if (!pricingInputValid || updatePricing.isPending) return;
    updatePricing.mutate();
  };

  const resolveSuccess = (order: Order) => {
    const requestId = window.prompt(
      "Enter the SMS-Man request ID verified in the provider dashboard:",
      order.provider_request_id ? String(order.provider_request_id) : "",
    );

    if (requestId === null) return;

    const phone = window.prompt(
      "Enter the confirmed phone number returned by SMS-Man:",
      order.phone_number ?? "",
    );

    if (phone === null) return;

    const cost = window.prompt("Enter the actual provider cost in NGN kobo:");

    if (cost === null) return;

    const note = window.prompt("Enter the audit note or evidence reference:");

    if (note === null) return;

    const parsedRequestId = parsePositiveInteger(requestId);
    const parsedCost = parsePositiveInteger(cost);

    if (
      parsedRequestId === null ||
      parsedCost === null ||
      !phone.trim() ||
      phone.trim().length > 40 ||
      note.trim().length < 8 ||
      note.trim().length > 200
    ) {
      window.alert(
        "Invalid details. Enter a valid request ID, a provider cost in whole kobo greater than zero, a phone number (up to 40 characters), and an audit note of 8-200 characters.",
      );
      return;
    }

    if (
      !window.confirm(
        `Confirm that order ${order.reference} was successful and that you verified the request ID, phone number, and actual provider cost directly with SMS-Man?`,
      )
    ) {
      return;
    }

    resolveOrder.mutate({
      id: order.id,
      body: {
        outcome: "SUCCESS",
        provider_request_id: parsedRequestId,
        phone_number: phone.trim(),
        provider_cost_kobo: parsedCost,
        note: note.trim(),
      },
    });
  };

  const resolveFailure = (order: Order) => {
    const note = window.prompt(
      "Enter evidence that SMS-Man definitively rejected or failed this purchase:",
    );

    if (note === null) return;

    // The backend accepts notes of 8-200 characters.
    if (note.trim().length < 8 || note.trim().length > 200) {
      window.alert("Provide an audit note between 8 and 200 characters.");
      return;
    }

    if (
      !window.confirm(
        `Confirm order ${order.reference} definitively failed? Only proceed if you verified the failure with SMS-Man. A timeout or lost response is not proof of failure. The customer's held funds will be refunded.`,
      )
    ) {
      return;
    }

    resolveOrder.mutate({
      id: order.id,
      body: {
        outcome: "FAILED",
        note: note.trim(),
      },
    });
  };

  const countries = catalogue?.countries ?? [];

  return (
    <div className="stack">
      <PageHead
        title="Virtual Numbers & eSIM operations"
        sub="Provider status and order investigation. Provider secrets are not displayed."
      />

      {!canViewOrders && (
        <Banner tone="error">
          You do not have permission to view virtual-number operations.
        </Banner>
      )}

      {/* Pricing configuration */}
      {canManagePricing && (
        <section className="card stack-sm">
          <h2 className="section-title">Virtual number pricing</h2>

          {pricing.isPending && <Skeleton h={80} />}

          {pricing.isError && (
            <Banner tone="error">{friendly(pricing.error)}</Banner>
          )}

          {pricing.data && (
            <>
              <Field label="Markup percentage">
                {(a) => (
                  <input
                    {...a}
                    className="input"
                    type="number"
                    min="0"
                    max={String(MAX_MARKUP)}
                    step="0.1"
                    value={markup}
                    onChange={(event) => setMarkup(event.target.value)}
                  />
                )}
              </Field>

              <Field label="Fixed fee (kobo)">
                {(a) => (
                  <input
                    {...a}
                    className="input"
                    type="number"
                    min="0"
                    step="1"
                    value={fee}
                    onChange={(event) => setFee(event.target.value)}
                  />
                )}
              </Field>

              <Field label="Minimum selling price (kobo)">
                {(a) => (
                  <input
                    {...a}
                    className="input"
                    type="number"
                    min="1"
                    step="1"
                    value={minPrice}
                    onChange={(event) => setMinPrice(event.target.value)}
                  />
                )}
              </Field>

              <Field label="Maximum selling price (kobo)">
                {(a) => (
                  <input
                    {...a}
                    className="input"
                    type="number"
                    min={minPrice}
                    step="1"
                    value={maxPrice}
                    onChange={(event) => setMaxPrice(event.target.value)}
                  />
                )}
              </Field>

              <label className="row">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                Enable sales (also requires backend SMSMAN_ENABLED)
              </label>

              {!pricingInputValid && (
                <Banner tone="error">
                  Check the pricing values. Markup must be between 0% and
                  500%. Fees must be non-negative whole kobo amounts, and
                  the maximum must be at least the minimum.
                </Banner>
              )}

              {updatePricing.isError && (
                <Banner tone="error">{friendly(updatePricing.error)}</Banner>
              )}

              {updatePricing.isSuccess && (
                <Banner tone="success">Pricing configuration saved.</Banner>
              )}

              <Button
                block
                loading={updatePricing.isPending}
                disabled={!pricingInputValid || updatePricing.isPending}
                onClick={handleSavePricing}
              >
                Save pricing
              </Button>
            </>
          )}
        </section>
      )}

      {/* Provider status */}
      {canManageProvider && status.isError && (
        <Banner tone="error">{friendly(status.error)}</Banner>
      )}

      {canManageProvider && status.isPending && <Skeleton h={100} />}

      {canManageProvider && status.data && (
        <section className="card stack-sm">
          <h2 className="section-title">SMS-Man provider</h2>

          <div className="row between">
            <span>Integration</span>
            <StatusBadge
              status={
                status.data.enabled &&
                status.data.configured &&
                status.data.ngn_rate_configured
                  ? "SUCCESSFUL"
                  : "PENDING"
              }
            />
          </div>

          <div className="row between">
            <span>Provider API version</span>
            <strong>{status.data.api_version || "Not reported"}</strong>
          </div>

          <div className="row between">
            <span>Configured</span>
            <strong>{status.data.configured ? "Yes" : "No"}</strong>
          </div>

          <div className="row between">
            <span>Provider integration enabled</span>
            <strong>{status.data.enabled ? "Yes" : "No"}</strong>
          </div>

          <div className="row between">
            <span>Provider currency</span>
            <strong>{status.data.currency || "Not reported"}</strong>
          </div>

          <div className="row between">
            <span>NGN conversion rate</span>
            <strong>
              {status.data.ngn_rate_configured ? "Configured" : "Missing"}
            </strong>
          </div>

          <div className="row between">
            <span>eSIM API</span>
            <strong>
              {status.data.esim_enabled
                ? "Enabled — verify provider support"
                : "Disabled"}
            </strong>
          </div>
        </section>
      )}

      {/* Provider catalogue */}
      {canManageProvider && (
        <section className="card stack-sm">
          <div className="row between">
            <h2 className="section-title">Provider catalogue</h2>
            <Button
              sm
              variant="secondary"
              loading={catalogueQuery.isFetching}
              disabled={catalogueQuery.isFetching}
              onClick={refreshCatalogue}
            >
              Refresh catalogue
            </Button>
          </div>

          <p className="muted small">
            Refresh the catalogue, then choose a country to load its prices.
            The first load for a country can take up to a minute because the
            provider is slow; repeat loads are cached for a few minutes.
          </p>

          {catalogueQuery.isError && (
            <Banner tone="error">
              {friendly(catalogueQuery.error)} The provider may still be
              responding. Wait a moment and press Refresh catalogue to try
              again; a finished lookup is cached and will load instantly.
            </Banner>
          )}

          <Field label="Country prices">
            {(a) => (
              <select
                {...a}
                className="input"
                value={catalogueCountry}
                onChange={(event) =>
                  selectCatalogueCountry(event.target.value)
                }
              >
                <option value="">
                  Catalogue only — select country for prices
                </option>
                {countries.map((country) => (
                  <option key={country.id} value={String(country.id)}>
                    {country.name}
                  </option>
                ))}
              </select>
            )}
          </Field>

          {catalogueQuery.isFetching && (
            <div className="stack-sm">
              <p className="muted small">
                Loading from the provider… this can take up to a minute.
              </p>
              <Skeleton h={48} />
              <Skeleton h={48} />
              <Skeleton h={48} />
            </div>
          )}

          {!catalogueRequested && !catalogueQuery.isFetching && (
            <p className="muted small">
              Select Refresh catalogue to load countries and services.
            </p>
          )}

          {catalogue && !catalogueQuery.isFetching && (
            <>
              <p className="muted small">
                Fetched{" "}
                {Number.isFinite(Date.parse(catalogue.fetched_at))
                  ? new Date(catalogue.fetched_at).toLocaleString()
                  : "at an unknown time"}
              </p>

              <div className="row between">
                <span>Countries returned</span>
                <strong>{catalogue.countries.length}</strong>
              </div>

              <div className="row between">
                <span>Services returned</span>
                <strong>{catalogue.services.length}</strong>
              </div>

              {catalogueCountry !== "" ? (
                catalogue.prices.length > 0 ? (
                  <div className="list">
                    {catalogue.prices.map((item) => (
                      <div
                        className="list-row"
                        key={`${item.application_id}-${item.service_name}`}
                      >
                        <span className="grow">
                          <strong>{item.service_name}</strong>

                          <span
                            className="muted small"
                            style={{ display: "block" }}
                          >
                            {item.available === true
                              ? `${item.inventory ?? 0} available`
                              : item.available === false
                                ? "Unavailable"
                                : "Stock unknown"}
                          </span>

                          {canSeeCosts && (
                            <span
                              className="muted small"
                              style={{ display: "block" }}
                            >
                              Provider cost:{" "}
                              {validKobo(item.provider_cost_kobo)
                                ? formatKobo(item.provider_cost_kobo)
                                : "Not available"}
                            </span>
                          )}
                        </span>

                        <span className="num">
                          {validKobo(item.price_kobo)
                            ? formatKobo(item.price_kobo)
                            : "Price unavailable"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <>
                    <Banner tone="error">
                      No priced services were returned for this country.
                      Check the backend price response, provider
                      application IDs, NGN conversion configuration, and
                      pricing rules.
                    </Banner>

                    <details>
                      <summary className="muted small">
                        Price diagnostics
                      </summary>
                      <pre
                        className="muted small"
                        style={{
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {catalogue.price_diagnostics
                          ? JSON.stringify(
                              catalogue.price_diagnostics,
                              null,
                              2,
                            )
                          : "price_diagnostics was not in the response."}
                      </pre>
                    </details>
                  </>
                )
              ) : (
                <p className="muted small">
                  Choose a country above to load its prices.
                </p>
              )}
            </>
          )}
        </section>
      )}

      {/* Revenue and margin report */}
      {canSeeCosts && (
        <section className="card stack-sm">
          <h2 className="section-title">Virtual Numbers report</h2>

          {report.isPending && <Skeleton h={100} />}

          {report.isError && (
            <Banner tone="error">{friendly(report.error)}</Banner>
          )}

          {report.data && (
            <>
              <div className="row between">
                <span>Orders</span>
                <strong>{report.data.orders}</strong>
              </div>

              <div className="row between">
                <span>Sales (NGN)</span>
                <strong>
                  {validKobo(report.data.sales_kobo)
                    ? formatKobo(report.data.sales_kobo)
                    : "Unavailable"}
                </strong>
              </div>

              <div className="row between">
                <span>Estimated supplier cost</span>
                <strong>
                  {validKobo(report.data.estimated_supplier_cost_kobo)
                    ? formatKobo(report.data.estimated_supplier_cost_kobo)
                    : "Unavailable"}
                </strong>
              </div>

              <div className="row between">
                <span>Estimated margin</span>
                <strong>
                  {validKobo(report.data.estimated_margin_kobo)
                    ? formatKobo(report.data.estimated_margin_kobo)
                    : "Unavailable"}
                </strong>
              </div>

              <p className="muted small">{report.data.note}</p>
            </>
          )}
        </section>
      )}

      {/* Order investigation */}
      {canViewOrders && (
        <>
          <h2 className="section-title">Virtual number orders</h2>

          <div className="row wrap">
            <input
              className="input"
              aria-label="Search orders"
              placeholder="Search order, number, customer…"
              value={searchOrders}
              onChange={(event) => setSearchOrders(event.target.value)}
            />

            <select
              className="input"
              aria-label="Filter by status"
              value={orderStatus}
              onChange={(event) => setOrderStatus(event.target.value)}
            >
              <option value="">All statuses</option>
              {ORDER_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>

          {orders.isError && (
            <Banner tone="error">{friendly(orders.error)}</Banner>
          )}

          {resolveOrder.isError && (
            <Banner tone="error">{friendly(resolveOrder.error)}</Banner>
          )}

          {resolveOrder.isSuccess && (
            <Banner tone="success">
              Resolution request accepted. The order list and report have
              been refreshed. Check the returned order status before taking
              further action.
            </Banner>
          )}

          {orders.isPending ? (
            <Skeleton h={120} />
          ) : (
            <div className="card flush list">
              {(orders.data ?? []).map((order) => (
                <div className="list-row" key={order.id}>
                  <div className="grow stack-sm">
                    <div className="row between">
                      <strong>{order.reference}</strong>
                      <StatusBadge status={order.status} />
                    </div>

                    <span className="muted small">
                      {order.country_name} · {order.service_name} · user{" "}
                      {order.user_id.slice(0, 8)}
                    </span>

                    <div className="row between">
                      <span>Customer price</span>
                      <strong>
                        {validKobo(order.price_kobo)
                          ? formatKobo(order.price_kobo)
                          : "Unavailable"}
                      </strong>
                    </div>

                    {canSeeCosts && order.provider_cost_kobo !== undefined && (
                      <>
                        <div className="row between">
                          <span>Provider cost estimate</span>
                          <span>
                            {validKobo(order.provider_cost_kobo)
                              ? formatKobo(order.provider_cost_kobo)
                              : "Unavailable"}
                          </span>
                        </div>

                        <div className="row between">
                          <span>Estimated margin (not realized profit)</span>
                          <span>
                            {validKobo(order.margin_kobo ?? 0)
                              ? formatKobo(order.margin_kobo ?? 0)
                              : "Unavailable"}
                          </span>
                        </div>
                      </>
                    )}

                    {order.provider_request_id != null && (
                      <span className="muted small">
                        Provider request: {order.provider_request_id}
                      </span>
                    )}

                    {order.phone_number && (
                      <span className="muted small">
                        Assigned number: {order.phone_number}
                      </span>
                    )}

                    {order.failure_reason && (
                      <span className="muted small">
                        {order.failure_reason}
                      </span>
                    )}

                    {canResolve && isReconcilable(order) && (
                      <div className="stack-sm">
                        <p className="muted small">
                          Verify the final provider outcome directly in
                          SMS-Man before resolving this order. A timeout or
                          lost response alone is not evidence of failure.
                        </p>

                        <div className="row wrap">
                          <Button
                            sm
                            variant="secondary"
                            loading={resolveOrder.isPending}
                            disabled={resolveOrder.isPending}
                            onClick={() => resolveSuccess(order)}
                          >
                            Confirm provider success
                          </Button>

                          <Button
                            sm
                            variant="danger"
                            loading={resolveOrder.isPending}
                            disabled={resolveOrder.isPending}
                            onClick={() => resolveFailure(order)}
                          >
                            Confirm failure & refund
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {!orders.data?.length && (
                <p className="muted" style={{ padding: "var(--s4)" }}>
                  No orders recorded.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}