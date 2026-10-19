import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
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

/**
 * Order lifecycle (the backend owns every transition):
 *
 *   PENDING / UNKNOWN  purchase in flight or being confirmed with provider
 *   ACTIVE             number assigned, money held, waiting for the code
 *   SMS_RECEIVED       code arrived, money captured, order is final
 *   EXPIRED            no code before expiry, hold released
 *   CANCELLED          cancelled before any code, hold released
 *   FAILED             purchase failed, hold released
 */
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
  /** When the provider assigned the number. */
  assigned_at?: string | null;
  /** After this time the number stops waiting for a code. */
  expires_at?: string | null;
  /** Server clock: first moment the customer may cancel. Preferred. */
  cancel_available_at?: string | null;
};

// The purchase response should carry the new order's id so the page can
// open it straight away. If it does not, the page finds the new order
// by comparing the orders list before and after the purchase.
type PurchaseResult = Txn & { order_id?: string | null };

type PricedService = {
  service: Service;
  price: Price;
};

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

// Where "Done" sends the customer. Change to your real route.
const TRANSACTIONS_PATH = "/activity";

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

// Calls that wait on the SMS-Man API (price lookups, purchase) can
// take far longer than the client's 20s default, so they use the
// slow-request timeout. Everything else keeps the default.
const SLOW = { timeoutMs: SLOW_REQUEST_TIMEOUT_MS };

// How often the orders list refreshes while something is in flight.
const WAITING_POLL_MS = 5_000;
const CONFIRMING_POLL_MS = 10_000;

/* ------------------------------------------------------------------ */
/* Styles                                                              */
/* ------------------------------------------------------------------ */

// Token names match the app's design system (--line, --accent, --r-md).
const palette = {
  border: "1px solid var(--line, rgba(255,255,255,0.14))",
  surface: "var(--surface-2, rgba(255,255,255,0.05))",
  accent: "var(--accent, #34d399)",
  radius: "var(--r-md, 14px)",
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

// A code has arrived. From this point the order is final: no cancel, no
// refund. The backend enforces the same rule; this only drives the UI.
function hasCode(order: Order): boolean {
  return (
    Boolean(order.sms_code) ||
    normaliseStatus(order.status) === "SMS_RECEIVED"
  );
}

// Number assigned, money held, still waiting for the code.
function isWaiting(order: Order): boolean {
  return normaliseStatus(order.status) === "ACTIVE" && !hasCode(order);
}

// Purchase still in flight or being confirmed with the provider.
function isConfirming(order: Order): boolean {
  const status = normaliseStatus(order.status);

  return status === "UNKNOWN" || status === "PENDING";
}

// Order has reached an end state, so the customer can move on.
function isFinished(order: Order): boolean {
  const status = normaliseStatus(order.status);

  return (
    hasCode(order) ||
    status === "FAILED" ||
    status === "EXPIRED" ||
    status === "CANCELLED"
  );
}

function badgeStatus(order: Order): string {
  if (hasCode(order)) return "SUCCESSFUL";
  if (isWaiting(order) || isConfirming(order)) return "PENDING";

  return normaliseStatus(order.status);
}

// 125000 -> "2:05"
function formatClock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const mm = Math.floor(total / 60);
  const ss = String(total % 60).padStart(2, "0");

  return `${mm}:${ss}`;
}

// Current time, ticking once a second only while `active`.
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;

    setNow(Date.now());

    const id = window.setInterval(() => setNow(Date.now()), 1000);

    return () => window.clearInterval(id);
  }, [active]);

  return now;
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
            color: done ? "var(--on-accent, #06251b)" : "inherit",
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
        borderBottom: "1px solid var(--line, rgba(255,255,255,0.08))",
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

function OrderRow({
  order,
  onOpen,
}: {
  order: Order;
  onOpen: () => void;
}) {
  const waiting = isWaiting(order);
  const confirming = isConfirming(order);

  return (
    <article className="card stack-sm">
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

        <StatusBadge status={badgeStatus(order)} />
      </div>

      <span className="muted small">
        {order.service_name} · {order.country_name}
      </span>

      {order.sms_code && (
        <div className="banner info">
          Verification code: <strong>{order.sms_code}</strong>
        </div>
      )}

      {waiting && (
        <span className="muted small">Waiting for the code…</span>
      )}

      {confirming && (
        <span className="muted small">
          Confirming with the provider. Please do not buy again yet.
        </span>
      )}

      {hasCode(order) && !order.sms_code && (
        <span className="muted small">Code received.</span>
      )}

      <div
        className="row between"
        style={{ alignItems: "center", gap: 12 }}
      >
        <span className="muted xs">
          {new Date(order.created_at).toLocaleString()} ·{" "}
          {formatKobo(order.price_kobo)}
        </span>

        <Button sm variant="secondary" onClick={onOpen}>
          Open
        </Button>
      </div>
    </article>
  );
}

function NumberView({
  order,
  loading,
  refreshing,
  onBack,
  onRefresh,
  onCopy,
  onDone,
}: {
  order: Order | undefined;
  loading: boolean;
  refreshing: boolean;
  onBack: () => void;
  onRefresh: () => void;
  onCopy: (value: string, message: string) => void;
  onDone: () => void;
}) {
  const waiting = order ? isWaiting(order) : false;
  const now = useNow(waiting);

  const backButton = (
    <div>
      <Button sm variant="secondary" onClick={onBack}>
        Back to numbers
      </Button>
    </div>
  );

  if (!order) {
    return (
      <>
        <PageHead
          title="Your number"
          sub="Get a temporary number to receive a verification code."
          back="/pay"
        />

        {backButton}

        {loading ? (
          <Skeleton h={160} />
        ) : (
          <Empty title="Number not found">
            It may still be loading. Go back and open it from My
            numbers.
          </Empty>
        )}
      </>
    );
  }

  const status = normaliseStatus(order.status);
  const received = hasCode(order);
  const confirming = isConfirming(order);
  const finished = isFinished(order);
  const refunded = order.refund_status === "REFUNDED";

  const expiresMs = order.expires_at
    ? new Date(order.expires_at).getTime() - now
    : null;

  return (
    <>
      <PageHead
        title="Your number"
        sub={`${order.service_name} · ${order.country_name}`}
        back="/pay"
      />

      {backButton}

      {/* ---------------- Number ---------------- */}
      <section className="card stack-sm">
        <div
          className="row between"
          style={{ alignItems: "center", gap: 12 }}
        >
          <span className="muted small">Phone number</span>
          <StatusBadge status={badgeStatus(order)} />
        </div>

        <strong
          className="num"
          style={{
            fontSize: "var(--t-xl, 28px)",
            overflowWrap: "anywhere",
          }}
        >
          {order.phone_number ?? "Awaiting number"}
        </strong>

        {order.phone_number && (waiting || received) && (
          <Button
            variant="secondary"
            onClick={() =>
              onCopy(order.phone_number ?? "", "Number copied")
            }
          >
            Copy number
          </Button>
        )}
      </section>

      {/* ---------------- Code received: final ---------------- */}
      {received && (
        <section
          className="card stack-sm"
          style={{ border: `1px solid ${palette.accent}` }}
        >
          <h2 className="section-title" style={{ margin: 0 }}>
            Verification code
          </h2>

          {order.sms_code ? (
            <>
              <strong
                className="num"
                style={{
                  fontSize: "var(--t-xl, 32px)",
                  letterSpacing: 3,
                  overflowWrap: "anywhere",
                }}
              >
                {order.sms_code}
              </strong>

              <Button
                variant="secondary"
                onClick={() =>
                  onCopy(order.sms_code ?? "", "Code copied")
                }
              >
                Copy code
              </Button>
            </>
          ) : (
            <div className="banner info">Code received.</div>
          )}

          <p className="muted small" style={{ margin: 0 }}>
            Your code was delivered, so this order is final and cannot
            be cancelled or refunded.
          </p>
        </section>
      )}

      {/* ---------------- Waiting for the code ---------------- */}
      {waiting && (
        <section className="card stack-sm">
          <h2 className="section-title" style={{ margin: 0 }}>
            Waiting for the code
          </h2>

          <div className="banner info">
            Use this number on {order.service_name} now. The code will
            appear here by itself.
          </div>

          {expiresMs !== null && !Number.isNaN(expiresMs) && (
            <span className="muted small">
              {expiresMs > 0 ? (
                <>
                  Number expires in{" "}
                  <strong className="num">{formatClock(expiresMs)}</strong>
                </>
              ) : (
                "Time is up. Updating…"
              )}
            </span>
          )}

          <span className="muted small">
            Your money is on hold. You are charged only if a code
            arrives.
          </span>

          <Button
            variant="secondary"
            loading={refreshing}
            disabled={refreshing}
            onClick={onRefresh}
          >
            Check now
          </Button>
        </section>
      )}

      {confirming && (
        <section className="card stack-sm">
          <h2 className="section-title" style={{ margin: 0 }}>
            Confirming your order
          </h2>

          <p className="muted small" style={{ margin: 0 }}>
            We are confirming this order with the provider. Please do
            not buy again yet. This page updates by itself.
          </p>
        </section>
      )}

      {(status === "FAILED" ||
        status === "EXPIRED" ||
        status === "CANCELLED") && (
        <section className="card stack-sm">
          <h2 className="section-title" style={{ margin: 0 }}>
            {status === "FAILED"
              ? "Order failed"
              : status === "EXPIRED"
                ? "No code arrived"
                : "Order cancelled"}
          </h2>

          {order.failure_reason && (
            <p className="small" style={{ margin: 0 }}>
              {order.failure_reason}
            </p>
          )}

          <p className="muted small" style={{ margin: 0 }}>
            {refunded
              ? "Your money has been returned to your wallet."
              : "Your held money is released once the provider confirms."}
          </p>
        </section>
      )}

      {/* ---------------- Done: go to transactions ---------------- */}
      {finished && (
        <Button block onClick={onDone}>
          {received ? "Done, view transactions" : "View transactions"}
        </Button>
      )}

      {/* ---------------- Details ---------------- */}
      <section className="card stack-sm">
        <div className="row between">
          <span className="muted">Price</span>
          <strong className="num">{formatKobo(order.price_kobo)}</strong>
        </div>

        <div className="row between">
          <span className="muted">Reference</span>
          <strong
            className="num"
            style={{ overflowWrap: "anywhere", textAlign: "right" }}
          >
            {order.reference}
          </strong>
        </div>

        <div className="row between">
          <span className="muted">Date</span>
          <span>{new Date(order.created_at).toLocaleString()}</span>
        </div>
      </section>
    </>
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
  // The number currently open on the in-page number screen.
  const [viewingId, setViewingId] = useState<string | null>(null);
  // Order created by the purchase in flight; opened when the sheet closes.
  const purchasedOrderId = useRef<string | null>(null);

  const { toast } = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

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

  // Polls while any number is waiting for a code (or being confirmed), so
  // the code shows up without the customer tapping anything. Polling
  // stops by itself once nothing is in flight. The backend must refresh
  // the provider state on this endpoint, or a worker/webhook must write
  // the code to the order.
  const orders = useQuery({
    queryKey: ["vnumber-orders"],
    queryFn: () =>
      api.get<Order[]>("/api/v1/virtual-numbers/orders"),
    retry: false,
    refetchInterval: (query) => {
      const data = query.state.data;

      if (!data) return false;
      if (data.some(isWaiting)) return WAITING_POLL_MS;
      if (data.some(isConfirming)) return CONFIRMING_POLL_MS;

      return false;
    },
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

  /* ---------------------------- effects ---------------------------- */

  // Tell the customer when a code arrives. Codes already present on the
  // first load are not announced.
  const seenCodes = useRef<Set<string> | null>(null);

  useEffect(() => {
    const data = orders.data;

    if (!data) return;

    const coded = data.filter((order) => Boolean(order.sms_code));

    if (seenCodes.current === null) {
      seenCodes.current = new Set(coded.map((order) => order.id));
      return;
    }

    for (const order of coded) {
      if (!seenCodes.current.has(order.id)) {
        seenCodes.current.add(order.id);
        toast("Code received");
      }
    }
  }, [orders.data, toast]);

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

  const viewingOrder =
    viewingId !== null
      ? orders.data?.find((item) => item.id === viewingId)
      : undefined;

  const globalError =
    countries.error ?? services.error ?? orders.error;

  const countryStepOpen = countryId === null || editingCountry;
  const serviceStepOpen = serviceId === null || editingService;

  /* ----------------------------- render ---------------------------- */

  return (
    <div className="stack">
      {viewingId !== null ? (
        <NumberView
          order={viewingOrder}
          loading={orders.isPending}
          refreshing={orders.isFetching}
          onBack={() => setViewingId(null)}
          onRefresh={() => void orders.refetch()}
          onCopy={copyText}
          onDone={() => {
            setViewingId(null);
            navigate(TRANSACTIONS_PATH);
          }}
        />
      ) : (
        <>
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
                <li>
                  Your money is held while we get your number. You are
                  charged only if a code arrives.
                </li>
                <li>
                  Your number opens on its own page, and the code appears
                  there by itself. Once it shows, the order is final and
                  cannot be refunded.
                </li>
                <li>
                  If no code arrives or the purchase fails, the hold is
                  released.
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
                {orders.data.map((order) => (
                  <OrderRow
                    key={order.id}
                    order={order}
                    onOpen={() => setViewingId(order.id)}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {selectedPrice && (
        <ReviewSheet
          navigateOnSuccess={false}
          open={review}
          onClose={() => {
            setReview(false);

            // After a purchase, open the number screen inline.
            if (purchasedOrderId.current) {
              setViewingId(purchasedOrderId.current);
              purchasedOrderId.current = null;
            }
          }}
          title="Review virtual number"
          lines={[
            ["Country", selectedPrice.country_name],
            ["Service", selectedPrice.service_name],
            ["Number", "Assigned after purchase"],
            ["Charged", "Only if a code arrives"],
          ]}
          total={formatKobo(selectedPrice.price_kobo)}
          note="The price is checked with the provider before your money is held. The hold is released if no code arrives. Once a code is delivered, the order is final and cannot be refunded. If the result is uncertain, the order stays under confirmation and must not be retried."
          onPriceChanged={(message) => {
            toast(message);
            void prices.refetch();
          }}
          submit={async ({ pinToken, idempotencyKey }) => {
            // Orders that existed before this purchase, used to find the
            // new one if the response does not carry its id.
            const before = new Set(
              (
                queryClient.getQueryData<Order[]>(["vnumber-orders"]) ??
                []
              ).map((item) => item.id),
            );

            try {
              const result = await api.post<PurchaseResult>(
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

              let orderId = result.order_id ?? null;

              // Fallback: the order that did not exist before.
              if (!orderId) {
                try {
                  const fresh = await queryClient.fetchQuery({
                    queryKey: ["vnumber-orders"],
                    queryFn: () =>
                      api.get<Order[]>("/api/v1/virtual-numbers/orders"),
                    staleTime: 0,
                  });

                  orderId =
                    fresh.find((item) => !before.has(item.id))?.id ?? null;
                } catch {
                  orderId = null;
                }
              }

              // Remember the new order. It opens when the sheet closes.
              purchasedOrderId.current = orderId;

              return result;
            } finally {
              // Whatever the outcome (success, failure, or "being
              // confirmed"), the order list must reflect it. This also
              // starts the code polling for a new active order.
              void queryClient.invalidateQueries({
                queryKey: ["vnumber-orders"],
              });
            }
          }}
        />
      )}
    </div>
  );
}
