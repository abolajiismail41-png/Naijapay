import { useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ReviewSheet } from "../components/ReviewSheet";
import {
  Banner,
  Button,
  Empty,
  PageHead,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { api, friendly, SLOW_REQUEST_TIMEOUT_MS } from "../lib/api";
import { formatKobo } from "../lib/money";
import { useToast } from "../components/Toast";
import type { Txn } from "../lib/types";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type Country = {
  id: number;
  name: string;
};

type Service = {
  id: number;
  name: string;
  code?: string | null;
};

type Price = {
  country_id: number;
  country_name: string;
  application_id: number;
  service_name: string;
  service_code?: string | null;
  provider_cost_kobo: number;
  price_kobo: number;
  price: string;
  available: boolean | null;
  inventory: number | null;
  currency: string;
};

type Order = {
  id: string;
  reference: string;
  status: string;
  transaction_status: string;
  country_name: string;
  service_name: string;
  phone_number?: string | null;
  price_kobo: number;
  price: string;
  sms_code?: string | null;
  refund_status?: string | null;
  failure_reason?: string | null;
  created_at: string;
};

type SmsResult = {
  order_id: string;
  status: string;
  sms_code?: string | null;
};

type PricedService = {
  service: Service;
  price: Price;
};

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const SERVICE_SEARCH_MIN_LENGTH = 2;
const MAX_SERVICE_RESULTS = 200;
const MAX_POPULAR_RESULTS = 12;

// Pickers show this many rows at once and scroll for the rest.
const ROW_HEIGHT = 56;
const VISIBLE_ROWS = 6;

// Services shown first, before the customer types anything.
const POPULAR_SERVICES = [
  "whatsapp",
  "telegram",
  "google",
  "facebook",
  "instagram",
  "tiktok",
  "twitter",
  "discord",
  "amazon",
  "paypal",
  "uber",
  "tinder",
];

// Calls that wait on the SMS-Man API (price lookups, purchase, SMS check,
// cancel) can take far longer than the client's 20s default, so they use the
// slow-request timeout. Everything else keeps the default.
const SLOW = { timeoutMs: SLOW_REQUEST_TIMEOUT_MS };

/* ------------------------------------------------------------------ */
/* Styles                                                              */
/* ------------------------------------------------------------------ */

const palette = {
  border: "1px solid var(--border, rgba(255,255,255,0.14))",
  surface: "var(--surface-2, rgba(255,255,255,0.05))",
  accent: "var(--primary, var(--accent, #34d399))",
  radius: "var(--r, 14px)",
};

const pickerBox: CSSProperties = {
  maxHeight: ROW_HEIGHT * VISIBLE_ROWS,
  overflowY: "auto",
  overscrollBehavior: "contain",
  WebkitOverflowScrolling: "touch",
  border: palette.border,
  borderRadius: palette.radius,
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function normaliseStatus(status: string): string {
  return status.trim().toUpperCase();
}

function stockLabel(price: Price): string {
  if (price.available === true) {
    return price.inventory == null
      ? "In stock"
      : `${price.inventory.toLocaleString()} in stock`;
  }

  if (price.available === false) return "Out of stock";

  return "Stock unknown";
}

function isPurchasable(price: Price | undefined): price is Price {
  return Boolean(
    price &&
      price.available === true &&
      Number.isSafeInteger(price.price_kobo) &&
      price.price_kobo > 0 &&
      Number.isSafeInteger(price.country_id) &&
      Number.isSafeInteger(price.application_id),
  );
}

function isPopular(name: string): boolean {
  const value = name.toLowerCase();

  return POPULAR_SERVICES.some((item) => value.includes(item));
}

/* ------------------------------------------------------------------ */
/* Small presentational components                                     */
/* ------------------------------------------------------------------ */

function StepHeader({
  step,
  title,
  done,
  action,
}: {
  step: number;
  title: string;
  done?: boolean;
  action?: ReactNode;
}) {
  return (
    <div
      className="row between"
      style={{ alignItems: "center", gap: 12 }}
    >
      <div className="row" style={{ alignItems: "center", gap: 10 }}>
        <span
          aria-hidden="true"
          style={{
            width: 26,
            height: 26,
            borderRadius: "50%",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 13,
            fontWeight: 700,
            background: done ? palette.accent : palette.surface,
            color: done ? "#06251b" : "inherit",
            border: done ? "none" : palette.border,
          }}
        >
          {done ? "✓" : step}
        </span>

        <h2 className="section-title" style={{ margin: 0 }}>
          {title}
        </h2>
      </div>

      {action}
    </div>
  );
}

function SearchBox({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <input
      className="input"
      type="search"
      aria-label={label}
      autoComplete="off"
      autoCorrect="off"
      spellCheck={false}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function PickerRow({
  title,
  subtitle,
  right,
  selected,
  disabled,
  onClick,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        width: "100%",
        minHeight: ROW_HEIGHT,
        boxSizing: "border-box",
        padding: "8px 14px",
        textAlign: "left",
        color: "inherit",
        font: "inherit",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        background: selected ? palette.surface : "transparent",
        border: 0,
        borderLeft: selected
          ? `3px solid ${palette.accent}`
          : "3px solid transparent",
        borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            display: "block",
            fontWeight: 600,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>

        {subtitle && (
          <span
            className="muted xs"
            style={{ display: "block" }}
          >
            {subtitle}
          </span>
        )}
      </span>

      {right && (
        <span className="num" style={{ fontWeight: 700 }}>
          {right}
        </span>
      )}
    </button>
  );
}

function ScrollHint({ count }: { count: number }) {
  if (count <= VISIBLE_ROWS) return null;

  return (
    <p className="muted xs" style={{ margin: 0 }}>
      {count.toLocaleString()} results · scroll to see more
    </p>
  );
}

function SummaryRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: () => void;
}) {
  return (
    <div
      className="row between"
      style={{
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        border: palette.border,
        borderRadius: palette.radius,
        background: palette.surface,
      }}
    >
      <span style={{ minWidth: 0 }}>
        <span className="muted xs" style={{ display: "block" }}>
          {label}
        </span>

        <strong
          style={{
            display: "block",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {value}
        </strong>
      </span>

      <Button sm variant="secondary" onClick={onChange}>
        Change
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function VirtualNumbers() {
  const [countryId, setCountryId] = useState<number | null>(null);
  const [serviceId, setServiceId] = useState<number | null>(null);
  const [countrySearch, setCountrySearch] = useState("");
  const [serviceSearch, setServiceSearch] = useState("");
  const [editingCountry, setEditingCountry] = useState(false);
  const [editingService, setEditingService] = useState(false);
  const [review, setReview] = useState(false);
  const [smsCode, setSmsCode] = useState<string | null>(null);

  const { toast } = useToast();
  const queryClient = useQueryClient();

  const countries = useQuery({
    queryKey: ["vnumber-countries"],
    queryFn: () =>
      api.get<Country[]>("/api/v1/virtual-numbers/countries"),
    retry: false,
  });

  const services = useQuery({
    queryKey: ["vnumber-services"],
    queryFn: () =>
      api.get<Service[]>("/api/v1/virtual-numbers/services"),
    retry: false,
  });

  const prices = useQuery({
    queryKey: ["vnumber-prices", countryId],
    enabled: countryId !== null,
    queryFn: () =>
      api.get<Price[]>(
        "/api/v1/virtual-numbers/prices",
        { country_id: countryId },
        SLOW,
      ),
    retry: false,
  });

  const orders = useQuery({
    queryKey: ["vnumber-orders"],
    queryFn: () =>
      api.get<Order[]>("/api/v1/virtual-numbers/orders"),
    retry: false,
  });

  /* ------------------------- derived data -------------------------- */

  const selectedCountry = useMemo(
    () => countries.data?.find((item) => item.id === countryId),
    [countries.data, countryId],
  );

  const filteredCountries = useMemo(() => {
    const query = countrySearch.trim().toLowerCase();

    return [...(countries.data ?? [])]
      .filter((item) =>
        query ? item.name.toLowerCase().includes(query) : true,
      )
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [countries.data, countrySearch]);

  const priceByApplication = useMemo(
    () =>
      new Map(
        (prices.data ?? []).map((item) => [
          item.application_id,
          item,
        ]),
      ),
    [prices.data],
  );

  // Only services that actually have a price for this country are shown.
  const pricedServices = useMemo<PricedService[]>(
    () =>
      (services.data ?? []).flatMap((service) => {
        const price = priceByApplication.get(service.id);

        return price ? [{ service, price }] : [];
      }),
    [services.data, priceByApplication],
  );

  const searching =
    serviceSearch.trim().length >= SERVICE_SEARCH_MIN_LENGTH;

  const visibleServices = useMemo(() => {
    const query = serviceSearch.trim().toLowerCase();

    const base = searching
      ? pricedServices.filter(
          ({ service }) =>
            service.name.toLowerCase().includes(query) ||
            (service.code ?? "").toLowerCase().includes(query),
        )
      : pricedServices.filter(({ service }) =>
          isPopular(service.name),
        );

    const ordered = [...base].sort((a, b) => {
      const aStock = a.price.available === true ? 0 : 1;
      const bStock = b.price.available === true ? 0 : 1;

      return (
        aStock - bStock ||
        a.service.name.localeCompare(b.service.name)
      );
    });

    return ordered.slice(
      0,
      searching ? MAX_SERVICE_RESULTS : MAX_POPULAR_RESULTS,
    );
  }, [pricedServices, serviceSearch, searching]);

  const selectedPrice =
    serviceId !== null ? priceByApplication.get(serviceId) : undefined;

  const selectedService =
    serviceId !== null
      ? services.data?.find((item) => item.id === serviceId)
      : undefined;

  /* ---------------------------- actions ---------------------------- */

  const chooseCountry = (id: number) => {
    setCountryId(id);
    setServiceId(null);
    setServiceSearch("");
    setCountrySearch("");
    setEditingCountry(false);
    setEditingService(false);
    setReview(false);
  };

  const chooseService = (id: number) => {
    setServiceId(id);
    setEditingService(false);
    setReview(false);
  };

  const copyText = (value: string, message: string) => {
    void navigator.clipboard
      .writeText(value)
      .then(() => toast(message))
      .catch(() => toast("Could not copy"));
  };

  const smsMutation = useMutation({
    mutationFn: (orderId: string) =>
      api.post<SmsResult>(
        `/api/v1/virtual-numbers/orders/${encodeURIComponent(orderId)}/sms`,
        undefined,
        SLOW,
      ),

    onSuccess: (result) => {
      setSmsCode(result.sms_code ?? null);

      toast(
        result.sms_code
          ? "Code received"
          : "No code yet. Try again in a few seconds.",
      );

      void queryClient.invalidateQueries({
        queryKey: ["vnumber-orders"],
      });
    },

    onError: (error) => {
      toast(friendly(error));
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) =>
      api.post<Order>(
        `/api/v1/virtual-numbers/orders/${encodeURIComponent(orderId)}/cancel`,
        undefined,
        SLOW,
      ),

    onSuccess: () => {
      toast("Cancellation request submitted");

      void queryClient.invalidateQueries({
        queryKey: ["vnumber-orders"],
      });
    },

    onError: (error) => {
      toast(friendly(error));
    },
  });

  const globalError =
    countries.error ?? services.error ?? orders.error;

  const countryStepOpen = countryId === null || editingCountry;
  const serviceStepOpen = serviceId === null || editingService;

  /* ----------------------------- render ---------------------------- */

  return (
    <div className="stack">
      <PageHead
        title="Virtual Numbers"
        sub="Get a temporary number to receive a verification code."
        back="/pay"
      />

      {globalError && (
        <Banner tone="error">{friendly(globalError)}</Banner>
      )}

      {/* ---------------- Step 1: country ---------------- */}
      <section className="card stack-sm">
        <StepHeader
          step={1}
          title="Choose a country"
          done={!countryStepOpen}
        />

        {countries.isPending && (
          <div className="stack-sm">
            <Skeleton h={44} />
            <Skeleton h={ROW_HEIGHT * 3} />
          </div>
        )}

        {countries.isError && (
          <div className="stack-sm">
            <p className="muted small">
              Countries could not be loaded.
            </p>

            <Button
              variant="secondary"
              onClick={() => void countries.refetch()}
            >
              Try again
            </Button>
          </div>
        )}

        {countries.data && !countryStepOpen && selectedCountry && (
          <SummaryRow
            label="Country"
            value={selectedCountry.name}
            onChange={() => setEditingCountry(true)}
          />
        )}

        {countries.data && countryStepOpen && (
          <>
            <SearchBox
              label="Search countries"
              placeholder="Search countries"
              value={countrySearch}
              onChange={setCountrySearch}
            />

            {filteredCountries.length === 0 ? (
              <Empty title="No matching country">
                Check the spelling or try another name.
              </Empty>
            ) : (
              <>
                <div
                  style={pickerBox}
                  role="group"
                  aria-label="Countries"
                >
                  {filteredCountries.map((item) => (
                    <PickerRow
                      key={item.id}
                      title={item.name}
                      selected={item.id === countryId}
                      onClick={() => chooseCountry(item.id)}
                    />
                  ))}
                </div>

                <ScrollHint count={filteredCountries.length} />
              </>
            )}
          </>
        )}
      </section>

      {/* ---------------- Step 2: service ---------------- */}
      {countryId !== null && !countryStepOpen && (
        <section className="card stack-sm">
          <StepHeader
            step={2}
            title="Choose a service"
            done={!serviceStepOpen && Boolean(selectedPrice)}
          />

          {services.isPending && (
            <div className="stack-sm">
              <Skeleton h={44} />
              <Skeleton h={ROW_HEIGHT * 3} />
            </div>
          )}

          {services.isError && (
            <div className="stack-sm">
              <p className="muted small">
                The service list could not be loaded.
              </p>

              <Button
                variant="secondary"
                onClick={() => void services.refetch()}
              >
                Try again
              </Button>
            </div>
          )}

          {prices.isPending && (
            <div className="stack-sm">
              <p className="muted small">
                Getting live prices for{" "}
                {selectedCountry?.name ?? "this country"}. The first
                load can take up to a minute.
              </p>
              <Skeleton h={ROW_HEIGHT} />
              <Skeleton h={ROW_HEIGHT} />
              <Skeleton h={ROW_HEIGHT} />
            </div>
          )}

          {prices.isError && (
            <div className="stack-sm">
              <Banner tone="error">{friendly(prices.error)}</Banner>

              <Button
                variant="secondary"
                onClick={() => void prices.refetch()}
              >
                Retry prices
              </Button>
            </div>
          )}

          {services.data && prices.data && !serviceStepOpen &&
            selectedService && (
              <SummaryRow
                label="Service"
                value={selectedService.name}
                onChange={() => setEditingService(true)}
              />
            )}

          {services.data && prices.data && serviceStepOpen && (
            <>
              <SearchBox
                label="Search services"
                placeholder={`Search ${pricedServices.length.toLocaleString()} services (e.g. WhatsApp)`}
                value={serviceSearch}
                onChange={setServiceSearch}
              />

              <p className="muted xs" style={{ margin: 0 }}>
                {searching
                  ? "Showing matching services with a price for this country."
                  : "Popular services. Type at least two letters to search them all."}
              </p>

              {visibleServices.length === 0 ? (
                <Empty
                  title={
                    searching
                      ? "No matching service"
                      : "Search for a service"
                  }
                >
                  {searching
                    ? "Try another name. Only services available in this country are listed."
                    : "Type a service name above to see its price."}
                </Empty>
              ) : (
                <>
                  <div
                    style={pickerBox}
                    role="group"
                    aria-label="Services"
                  >
                    {visibleServices.map(({ service, price }) => (
                      <PickerRow
                        key={service.id}
                        title={service.name}
                        subtitle={stockLabel(price)}
                        right={
                          price.available === false
                            ? undefined
                            : formatKobo(price.price_kobo)
                        }
                        selected={service.id === serviceId}
                        disabled={!isPurchasable(price)}
                        onClick={() => chooseService(service.id)}
                      />
                    ))}
                  </div>

                  <ScrollHint count={visibleServices.length} />
                </>
              )}
            </>
          )}
        </section>
      )}

      {/* ---------------- Step 3: review ---------------- */}
      {selectedPrice && !serviceStepOpen && !countryStepOpen && (
        <section
          className="card stack-sm"
          style={{ border: `1px solid ${palette.accent}` }}
        >
          <StepHeader step={3} title="Your order" />

          <div className="stack-sm">
            <div className="row between">
              <span className="muted">Country</span>
              <strong>{selectedPrice.country_name}</strong>
            </div>

            <div className="row between">
              <span className="muted">Service</span>
              <strong>{selectedPrice.service_name}</strong>
            </div>

            <div className="row between">
              <span className="muted">Availability</span>
              <strong>{stockLabel(selectedPrice)}</strong>
            </div>
          </div>

          <div
            className="row between"
            style={{
              alignItems: "center",
              paddingTop: 12,
              borderTop: palette.border,
            }}
          >
            <span className="muted">Total</span>

            <strong
              className="num"
              style={{ fontSize: "var(--t-xl, 24px)" }}
            >
              {formatKobo(selectedPrice.price_kobo)}
            </strong>
          </div>

          <ul
            className="muted small"
            style={{ margin: 0, paddingLeft: 18 }}
          >
            <li>The number is shown after you pay.</li>
            <li>
              If the purchase fails, your wallet is refunded
              automatically.
            </li>
            <li>Buying can take up to a minute. Keep this page open.</li>
          </ul>

          <Button
            block
            disabled={!isPurchasable(selectedPrice)}
            onClick={() => setReview(true)}
          >
            Continue to payment
          </Button>
        </section>
      )}

      {selectedPrice && (
        <ReviewSheet
          open={review}
          onClose={() => setReview(false)}
          title="Review virtual number"
          lines={[
            ["Country", selectedPrice.country_name],
            ["Service", selectedPrice.service_name],
            ["Number", "Assigned after purchase"],
          ]}
          total={formatKobo(selectedPrice.price_kobo)}
          note="The price is checked with the provider before your wallet is charged. If the result is uncertain, the order stays under confirmation and must not be retried."
          onPriceChanged={(message) => {
            toast(message);
            void prices.refetch();
          }}
          submit={async ({ pinToken, idempotencyKey }) => {
            try {
              return await api.post<Txn>(
                "/api/v1/virtual-numbers/orders",
                {
                  country_id: selectedPrice.country_id,
                  application_id: selectedPrice.application_id,
                  confirmed_price_kobo: selectedPrice.price_kobo,
                },
                {
                  pinToken,
                  idempotencyKey,
                  // The purchase waits on SMS-Man and can run long. The
                  // idempotency key makes a retry safe.
                  timeoutMs: SLOW_REQUEST_TIMEOUT_MS,
                },
              );
            } finally {
              // Whatever the outcome (success, failure, or "being
              // confirmed"), the order list must reflect it.
              void queryClient.invalidateQueries({
                queryKey: ["vnumber-orders"],
              });
            }
          }}
        />
      )}

      {/* ---------------- Received code ---------------- */}
      {smsCode && (
        <section
          className="card stack-sm"
          style={{ border: `1px solid ${palette.accent}` }}
        >
          <h2 className="section-title" style={{ margin: 0 }}>
            Your verification code
          </h2>

          <strong
            className="num"
            style={{
              fontSize: "var(--t-xl, 28px)",
              letterSpacing: 2,
            }}
          >
            {smsCode}
          </strong>

          <Button
            variant="secondary"
            onClick={() => copyText(smsCode, "Code copied")}
          >
            Copy code
          </Button>
        </section>
      )}

      {/* ---------------- My numbers ---------------- */}
      <section className="stack-sm">
        <h2 className="section-title">My numbers</h2>

        {orders.isPending ? (
          <div className="stack">
            <Skeleton h={96} />
            <Skeleton h={96} />
          </div>
        ) : orders.isError ? (
          <div className="stack-sm">
            <p className="muted small">
              Your orders could not be loaded.
            </p>

            <Button
              variant="secondary"
              onClick={() => void orders.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : !orders.data?.length ? (
          <Empty title="No numbers yet">
            Numbers you buy will appear here.
          </Empty>
        ) : (
          <div className="stack-sm">
            {orders.data.map((order) => {
              const status = normaliseStatus(order.status);
              const active =
                status === "ACTIVE" || status === "SMS_RECEIVED";
              const uncertain =
                status === "UNKNOWN" || status === "PENDING";
              const canCheckSms =
                Boolean(order.phone_number) && active;
              const canCancel =
                Boolean(order.phone_number) &&
                ["ACTIVE", "SMS_RECEIVED"].includes(status);

              return (
                <article
                  key={order.id}
                  className="card stack-sm"
                >
                  <div
                    className="row between"
                    style={{ alignItems: "center", gap: 12 }}
                  >
                    <strong
                      className="num"
                      style={{ fontSize: "var(--t-lg, 18px)" }}
                    >
                      {order.phone_number ?? "Awaiting number"}
                    </strong>

                    <StatusBadge
                      status={
                        active
                          ? "SUCCESSFUL"
                          : uncertain
                            ? "PENDING"
                            : status
                      }
                    />
                  </div>

                  <span className="muted small">
                    {order.service_name} · {order.country_name}
                  </span>

                  <div className="row between">
                    <span className="muted xs">
                      {new Date(order.created_at).toLocaleString()}
                    </span>

                    <strong className="num">
                      {formatKobo(order.price_kobo)}
                    </strong>
                  </div>

                  {order.sms_code && (
                    <div className="banner info">
                      Verification code:{" "}
                      <strong>{order.sms_code}</strong>
                    </div>
                  )}

                  {order.failure_reason && (
                    <span className="small">
                      {order.failure_reason}
                    </span>
                  )}

                  {uncertain && (
                    <span className="muted small">
                      We are confirming this order with the
                      provider. Please do not buy again yet.
                    </span>
                  )}

                  {status === "FAILED" &&
                    order.refund_status === "REFUNDED" && (
                      <span className="muted small">
                        This order failed and your wallet has been
                        refunded.
                      </span>
                    )}

                  {status === "CANCELLED" && (
                    <span className="muted small">
                      Cancelled. Refund eligibility depends on the
                      confirmed provider outcome.
                    </span>
                  )}

                  {(canCheckSms || canCancel || order.phone_number) && (
                    <div className="row wrap" style={{ gap: 8 }}>
                      {order.phone_number && (
                        <Button
                          sm
                          variant="secondary"
                          onClick={() =>
                            copyText(
                              order.phone_number ?? "",
                              "Number copied",
                            )
                          }
                        >
                          Copy number
                        </Button>
                      )}

                      {canCheckSms && (
                        <Button
                          sm
                          loading={smsMutation.isPending}
                          disabled={smsMutation.isPending}
                          onClick={() => {
                            setSmsCode(null);
                            smsMutation.mutate(order.id);
                          }}
                        >
                          Get code
                        </Button>
                      )}

                      {canCancel && (
                        <Button
                          sm
                          variant="danger"
                          loading={cancelMutation.isPending}
                          disabled={cancelMutation.isPending}
                          onClick={() => {
                            if (
                              window.confirm(
                                "Cancel this number? Cancellation does not guarantee a refund.",
                              )
                            ) {
                              cancelMutation.mutate(order.id);
                            }
                          }}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
