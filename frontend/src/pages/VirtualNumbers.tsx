import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
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
import type { Txn } from "../lib/types";

import "./VirtualNumbers.css";

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
 *   CANCELLED          closed by the backend, hold released
 *   FAILED             purchase failed, hold released
 *
 * Customers cannot cancel a number. An order without a code simply expires
 * and the backend releases the hold.
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
};

// The purchase response should carry the new order's id so the page can
// open it straight away. If it does not, the page falls back to matching
// the order by transaction reference.
type PurchaseResult = Txn & { order_id?: string | null };

type PricedService = {
  service: Service;
  price: Price;
};

type StockState = "in" | "out" | "unknown";

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const SERVICE_SEARCH_MIN_LENGTH = 2;
const MAX_SERVICE_RESULTS = 200;
const MAX_POPULAR_RESULTS = 12;
const PICKER_VISIBLE_ROWS = 6;

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

// Calls that wait on the SMS-Man API (price lookups, purchase) can take far
// longer than the client's 20s default, so they use the slow-request
// timeout. Everything else keeps the default.
const SLOW = { timeoutMs: SLOW_REQUEST_TIMEOUT_MS };

// How often the orders list refreshes while something is in flight.
const WAITING_POLL_MS = 5_000;
const CONFIRMING_POLL_MS = 10_000;

// Order states that will not change again.
const FINAL_STATUSES = new Set(["SMS_RECEIVED", "EXPIRED", "CANCELLED", "FAILED"]);

const ORDERS_KEY = ["vnumber-orders"] as const;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function normaliseStatus(status: string): string {
  return status.trim().toUpperCase();
}

// A code has arrived. From this point the order is final. The backend
// enforces the same rule; this only drives the UI.
function hasCode(order: Order): boolean {
  return (
    Boolean(order.sms_code) || normaliseStatus(order.status) === "SMS_RECEIVED"
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

function isEnded(order: Order): boolean {
  const status = normaliseStatus(order.status);

  return status === "FAILED" || status === "EXPIRED" || status === "CANCELLED";
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

function stockState(price: Price): StockState {
  if (price.available === true) return "in";
  if (price.available === false) return "out";

  return "unknown";
}

function stockLabel(price: Price): string {
  const state = stockState(price);

  if (state === "in") {
    return price.inventory == null
      ? "In stock"
      : `${price.inventory.toLocaleString()} in stock`;
  }

  return state === "out" ? "Out of stock" : "Stock unknown";
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

function byNewest(a: Order, b: Order): number {
  return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
}

/* ------------------------------------------------------------------ */
/* Small presentational components                                     */
/* ------------------------------------------------------------------ */

function Stepper({ current }: { current: 1 | 2 | 3 }) {
  const steps = ["Country", "Service", "Review"];

  return (
    <ol className="vn-steps" aria-label="Order progress">
      {steps.map((label, index) => {
        const step = index + 1;
        const state =
          step < current ? "done" : step === current ? "current" : "todo";

        return (
          <li
            key={label}
            className="vn-step"
            data-state={state}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className="vn-step-dot" aria-hidden="true">
              {state === "done" ? "✓" : step}
            </span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function CardHead({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="vn-card-head">
      <h2 className="vn-card-title">{title}</h2>
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
      className="input vn-search"
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
  stock,
  right,
  selected,
  disabled,
  onClick,
}: {
  title: string;
  subtitle?: string;
  stock?: StockState;
  right?: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="vn-row"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="vn-row-main">
        <span className="vn-row-title">{title}</span>

        {subtitle && (
          <span className="vn-row-sub" data-stock={stock}>
            {stock && <i className="vn-dot" aria-hidden="true" />}
            {subtitle}
          </span>
        )}
      </span>

      {right && <span className="vn-row-right num">{right}</span>}

      {selected && (
        <span className="vn-row-check" aria-hidden="true">
          ✓
        </span>
      )}
    </button>
  );
}

function ScrollHint({ count }: { count: number }) {
  if (count <= PICKER_VISIBLE_ROWS) return null;

  return (
    <p className="vn-hint">
      {count.toLocaleString()} results. Scroll to see more.
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
    <div className="vn-summary">
      <span className="vn-summary-text">
        <span className="vn-summary-label">{label}</span>
        <span className="vn-summary-value">{value}</span>
      </span>

      <Button sm variant="secondary" onClick={onChange}>
        Change
      </Button>
    </div>
  );
}

function PickerSkeleton() {
  return (
    <div className="stack-sm">
      <Skeleton h={44} />
      <Skeleton h={56} />
      <Skeleton h={56} />
      <Skeleton h={56} />
    </div>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="vn-kv-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* My numbers: list row                                                */
/* ------------------------------------------------------------------ */

function OrderRow({ order, onOpen }: { order: Order; onOpen: () => void }) {
  const waiting = isWaiting(order);
  const confirming = isConfirming(order);
  const received = hasCode(order);

  return (
    <article className="vn-order">
      <div className="vn-between">
        <strong className="vn-order-number">
          {order.phone_number ?? "Assigning number"}
        </strong>
        <StatusBadge status={badgeStatus(order)} />
      </div>

      <span className="muted small">
        {order.service_name} · {order.country_name}
      </span>

      {order.sms_code && (
        <div className="vn-code-chip">
          <span className="small">Code</span>
          <strong>{order.sms_code}</strong>
        </div>
      )}

      {waiting && <span className="muted small">Waiting for the code…</span>}

      {confirming && (
        <span className="muted small">
          Confirming with the provider. Please do not buy again yet.
        </span>
      )}

      {received && !order.sms_code && (
        <span className="muted small">Code received.</span>
      )}

      <div className="vn-order-foot">
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

/* ------------------------------------------------------------------ */
/* Number page (inline)                                                */
/* ------------------------------------------------------------------ */

function NumberView({
  order,
  loading,
  refreshing,
  onBack,
  onRefresh,
  onCopy,
}: {
  order: Order | undefined;
  loading: boolean;
  refreshing: boolean;
  onBack: () => void;
  onRefresh: () => void;
  onCopy: (value: string, message: string) => void;
}) {
  const waiting = order ? isWaiting(order) : false;
  const now = useNow(waiting);

  const back = (
    <button type="button" className="vn-back" onClick={onBack}>
      <span aria-hidden="true">←</span> All numbers
    </button>
  );

  if (!order) {
    return (
      <>
        <PageHead
          title="Your number"
          sub="Receive your verification code here."
          back="/pay"
        />

        {back}

        {loading ? (
          <Skeleton h={160} />
        ) : (
          <Empty title="Number not found">
            It may still be loading. Go back and open it from My numbers.
          </Empty>
        )}
      </>
    );
  }

  const received = hasCode(order);
  const confirming = isConfirming(order);
  const ended = isEnded(order);
  const status = normaliseStatus(order.status);
  const refunded = order.refund_status === "REFUNDED";
  const canCopyNumber = Boolean(order.phone_number) && (waiting || received);

  // Countdown and progress bar (share of the waiting window left).
  const expiresAt = order.expires_at ? new Date(order.expires_at).getTime() : NaN;
  const startedAt = new Date(order.assigned_at ?? order.created_at).getTime();
  const remainingMs = Number.isNaN(expiresAt) ? null : expiresAt - now;
  const windowMs =
    Number.isNaN(expiresAt) || Number.isNaN(startedAt)
      ? null
      : expiresAt - startedAt;
  const leftShare =
    remainingMs !== null && windowMs !== null && windowMs > 0
      ? Math.min(1, Math.max(0, remainingMs / windowMs))
      : null;

  const endedTitle =
    status === "FAILED"
      ? "Order failed"
      : status === "EXPIRED"
        ? "No code arrived"
        : "Order closed";

  return (
    <>
      <PageHead
        title="Your number"
        sub={`${order.service_name} · ${order.country_name}`}
        back="/pay"
      />

      {back}

      {/* ---------------- Number ---------------- */}
      <section className="vn-card">
        <div className="vn-between">
          <span className="muted small">Phone number</span>
          <StatusBadge status={badgeStatus(order)} />
        </div>

        <strong className="vn-number">
          {order.phone_number ?? "Assigning number…"}
        </strong>

        {canCopyNumber && (
          <Button
            block
            variant="secondary"
            onClick={() => onCopy(order.phone_number ?? "", "Number copied")}
          >
            Copy number
          </Button>
        )}
      </section>

      {/* ---------------- Waiting for the code ---------------- */}
      {waiting && (
        <section className="vn-card" aria-live="polite">
          <div className="vn-status">
            <span className="vn-pulse" aria-hidden="true" />

            <div className="vn-status-text">
              <h2 className="vn-card-title">Waiting for your code</h2>
              <p className="vn-hint">
                Use this number on {order.service_name} now. The code appears
                here by itself.
              </p>
            </div>
          </div>

          {remainingMs !== null && (
            <>
              {leftShare !== null && (
                <div
                  className="vn-progress"
                  role="progressbar"
                  aria-label="Time left for this number"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(leftShare * 100)}
                >
                  <span style={{ width: `${leftShare * 100}%` }} />
                </div>
              )}

              <div className="vn-countdown">
                {remainingMs > 0 ? (
                  <>
                    <span className="muted">Number expires in</span>
                    <strong>{formatClock(remainingMs)}</strong>
                  </>
                ) : (
                  <span className="muted">Time is up. Updating…</span>
                )}
              </div>
            </>
          )}

          <p className="vn-hint">
            Your money is on hold. You are charged only if a code arrives.
          </p>

          <Button
            block
            variant="secondary"
            loading={refreshing}
            disabled={refreshing}
            onClick={onRefresh}
          >
            Check now
          </Button>
        </section>
      )}

      {/* ---------------- Code received: final ---------------- */}
      {received && (
        <section className="vn-card" data-emphasis="true">
          <CardHead title="Verification code" />

          {order.sms_code ? (
            <>
              <strong className="vn-code">{order.sms_code}</strong>

              <Button
                block
                onClick={() => onCopy(order.sms_code ?? "", "Code copied")}
              >
                Copy code
              </Button>
            </>
          ) : (
            <div className="banner info">Code received.</div>
          )}

          <p className="vn-hint">
            Your code was delivered, so this order is complete and cannot be
            refunded. It now appears in your transactions.
          </p>
        </section>
      )}

      {/* ---------------- Confirming ---------------- */}
      {confirming && (
        <section className="vn-card" aria-live="polite">
          <CardHead title="Confirming your order" />

          <p className="vn-hint">
            We are confirming this order with the provider. Please do not buy
            again yet. This page updates by itself.
          </p>
        </section>
      )}

      {/* ---------------- Ended without a code ---------------- */}
      {ended && (
        <section className="vn-card">
          <CardHead title={endedTitle} />

          {order.failure_reason && <p className="small">{order.failure_reason}</p>}

          <p className="vn-hint">
            {refunded
              ? "Your money has been returned to your wallet."
              : "Your held money is released once the provider confirms."}
          </p>
        </section>
      )}

      {/* ---------------- Details ---------------- */}
      <section className="vn-card">
        <CardHead title="Order details" />

        <dl className="vn-kv">
          <Detail label="Price">
            <span className="num">{formatKobo(order.price_kobo)}</span>
          </Detail>
          <Detail label="Reference">
            <span className="num">{order.reference}</span>
          </Detail>
          <Detail label="Date">
            {new Date(order.created_at).toLocaleString()}
          </Detail>
        </dl>

        {(received || ended) && (
          <Link
            className="vn-link"
            to={`/activity/${encodeURIComponent(order.reference)}`}
          >
            View in Activity
          </Link>
        )}
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
  // True once a purchase succeeded and the review sheet has not closed yet.
  const purchased = useRef(false);

  const { toast } = useToast();
  const queryClient = useQueryClient();

  const countries = useQuery({
    queryKey: ["vnumber-countries"],
    queryFn: () => api.get<Country[]>("/api/v1/virtual-numbers/countries"),
    retry: false,
  });

  const services = useQuery({
    queryKey: ["vnumber-services"],
    queryFn: () => api.get<Service[]>("/api/v1/virtual-numbers/services"),
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
  // the code shows up without the customer tapping anything. Polling stops
  // by itself once nothing is in flight. The backend must refresh the
  // provider state on this endpoint, or a worker/webhook must write the
  // code to the order.
  const orders = useQuery({
    queryKey: ORDERS_KEY,
    queryFn: () => api.get<Order[]>("/api/v1/virtual-numbers/orders"),
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
      .filter((item) => (query ? item.name.toLowerCase().includes(query) : true))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [countries.data, countrySearch]);

  const priceByApplication = useMemo(
    () => new Map((prices.data ?? []).map((item) => [item.application_id, item])),
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

  const searching = serviceSearch.trim().length >= SERVICE_SEARCH_MIN_LENGTH;

  const visibleServices = useMemo(() => {
    const query = serviceSearch.trim().toLowerCase();

    const base = searching
      ? pricedServices.filter(
          ({ service }) =>
            service.name.toLowerCase().includes(query) ||
            (service.code ?? "").toLowerCase().includes(query),
        )
      : pricedServices.filter(({ service }) => isPopular(service.name));

    const ordered = [...base].sort((a, b) => {
      const aStock = a.price.available === true ? 0 : 1;
      const bStock = b.price.available === true ? 0 : 1;

      return aStock - bStock || a.service.name.localeCompare(b.service.name);
    });

    return ordered.slice(0, searching ? MAX_SERVICE_RESULTS : MAX_POPULAR_RESULTS);
  }, [pricedServices, serviceSearch, searching]);

  const selectedPrice =
    serviceId !== null ? priceByApplication.get(serviceId) : undefined;

  const selectedService =
    serviceId !== null
      ? services.data?.find((item) => item.id === serviceId)
      : undefined;

  const sortedOrders = useMemo(
    () => [...(orders.data ?? [])].sort(byNewest),
    [orders.data],
  );

  const viewingOrder =
    viewingId !== null
      ? orders.data?.find((item) => item.id === viewingId)
      : undefined;

  const countryStepOpen = countryId === null || editingCountry;
  const serviceStepOpen =
    serviceId === null ||
    editingService ||
    (Boolean(prices.data) && !selectedPrice);

  const currentStep: 1 | 2 | 3 = countryStepOpen
    ? 1
    : serviceStepOpen || !selectedPrice
      ? 2
      : 3;

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

  // The backend records the transaction (hold, then capture or release).
  // When an order reaches a final state, refresh the transaction list and
  // wallet so Activity is up to date without the customer doing anything.
  const lastStatuses = useRef<Map<string, string> | null>(null);

  useEffect(() => {
    const data = orders.data;

    if (!data) return;

    const next = new Map(
      data.map((order) => [order.id, normaliseStatus(order.status)]),
    );
    const previous = lastStatuses.current;

    lastStatuses.current = next;

    if (!previous) return;

    const settled = data.some((order) => {
      const current = normaliseStatus(order.status);

      return previous.get(order.id) !== current && FINAL_STATUSES.has(current);
    });

    if (settled) {
      void queryClient.invalidateQueries({ queryKey: ["txns"] });
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
    }
  }, [orders.data, queryClient]);

  // Start every screen change at the top.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [viewingId]);

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

  const copyText = async (value: string, message: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast(message);
    } catch {
      toast("Could not copy");
    }
  };

  const closeReview = () => {
    setReview(false);

    // After a purchase, clear the service so the same order cannot be
    // submitted twice by accident. The country stays selected.
    if (purchased.current) {
      purchased.current = false;
      setServiceId(null);
      setServiceSearch("");
    }
  };

  /* ----------------------------- render ---------------------------- */

  if (viewingId !== null) {
    return (
      <div className="vn">
        <NumberView
          order={viewingOrder}
          loading={orders.isPending || (orders.isFetching && !viewingOrder)}
          refreshing={orders.isFetching}
          onBack={() => setViewingId(null)}
          onRefresh={() => void orders.refetch()}
          onCopy={(value, message) => void copyText(value, message)}
        />
      </div>
    );
  }

  return (
    <div className="vn">
      <PageHead
        title="Virtual Numbers"
        sub="Get a temporary number to receive a verification code."
        back="/pay"
      />

      <Stepper current={currentStep} />

      {/* ---------------- Step 1: country ---------------- */}
      <section className="vn-card">
        <CardHead title="Choose a country" />

        {countries.isPending && <PickerSkeleton />}

        {countries.isError && (
          <div className="stack-sm">
            <Banner tone="error">{friendly(countries.error)}</Banner>

            <Button variant="secondary" onClick={() => void countries.refetch()}>
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
                <div className="vn-list" role="group" aria-label="Countries">
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
        <section className="vn-card">
          <CardHead title="Choose a service" />

          {(services.isPending || prices.isPending) && !prices.isError && (
            <div className="stack-sm">
              <p className="vn-hint">
                Getting live prices for{" "}
                {selectedCountry?.name ?? "this country"}. The first load can
                take up to a minute.
              </p>
              <Skeleton h={56} />
              <Skeleton h={56} />
              <Skeleton h={56} />
            </div>
          )}

          {services.isError && (
            <div className="stack-sm">
              <Banner tone="error">{friendly(services.error)}</Banner>

              <Button variant="secondary" onClick={() => void services.refetch()}>
                Try again
              </Button>
            </div>
          )}

          {prices.isError && (
            <div className="stack-sm">
              <Banner tone="error">{friendly(prices.error)}</Banner>

              <Button variant="secondary" onClick={() => void prices.refetch()}>
                Retry prices
              </Button>
            </div>
          )}

          {services.data && prices.data && !serviceStepOpen && selectedService && (
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
                placeholder={`Search ${pricedServices.length.toLocaleString()} services`}
                value={serviceSearch}
                onChange={setServiceSearch}
              />

              <p className="vn-hint">
                {searching
                  ? "Showing matching services with a price for this country."
                  : "Popular services. Type at least two letters to search them all."}
              </p>

              {visibleServices.length === 0 ? (
                <Empty
                  title={searching ? "No matching service" : "Search for a service"}
                >
                  {searching
                    ? "Try another name. Only services available in this country are listed."
                    : "Type a service name above to see its price."}
                </Empty>
              ) : (
                <>
                  <div className="vn-list" role="group" aria-label="Services">
                    {visibleServices.map(({ service, price }) => (
                      <PickerRow
                        key={service.id}
                        title={service.name}
                        subtitle={stockLabel(price)}
                        stock={stockState(price)}
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
        <section className="vn-card" data-emphasis="true">
          <CardHead title="Your order" />

          <dl className="vn-kv">
            <Detail label="Country">{selectedPrice.country_name}</Detail>
            <Detail label="Service">{selectedPrice.service_name}</Detail>
            <Detail label="Availability">{stockLabel(selectedPrice)}</Detail>
          </dl>

          <div className="vn-total">
            <span className="muted">Total</span>
            <strong className="num">{formatKobo(selectedPrice.price_kobo)}</strong>
          </div>

          <ul className="vn-notes">
            <li>
              Your money is held while we get your number. You are charged only
              if a code arrives.
            </li>
            <li>
              Your number opens on its own page, and the code appears there by
              itself.
            </li>
            <li>
              If the number expires without a code, or the purchase fails, the
              hold is released. Once a code arrives, the order is final.
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
      <section className="vn-orders" aria-label="My numbers">
        <h2 className="vn-section-title">My numbers</h2>

        {orders.isPending ? (
          <div className="stack-sm">
            <Skeleton h={96} />
            <Skeleton h={96} />
          </div>
        ) : orders.isError ? (
          <div className="stack-sm">
            <Banner tone="error">{friendly(orders.error)}</Banner>

            <Button variant="secondary" onClick={() => void orders.refetch()}>
              Try again
            </Button>
          </div>
        ) : sortedOrders.length === 0 ? (
          <Empty title="No numbers yet">
            Numbers you buy will appear here.
          </Empty>
        ) : (
          sortedOrders.map((order) => (
            <OrderRow
              key={order.id}
              order={order}
              onOpen={() => setViewingId(order.id)}
            />
          ))
        )}
      </section>

      {selectedPrice && (
        <ReviewSheet
          open={review}
          navigateOnSuccess={false}
          recheckLabel="My numbers"
          onClose={closeReview}
          title="Review virtual number"
          lines={[
            ["Country", selectedPrice.country_name],
            ["Service", selectedPrice.service_name],
            ["Number", "Assigned after purchase"],
            ["Charged", "Only if a code arrives"],
          ]}
          total={formatKobo(selectedPrice.price_kobo)}
          note="The price is checked with the provider before your money is held. The hold is released if no code arrives before the number expires. Once a code is delivered, the order is final and cannot be refunded. If the result is uncertain, the order stays under confirmation and must not be retried."
          onPriceChanged={(message) => {
            toast(message);
            void prices.refetch();
          }}
          submit={async ({ pinToken, idempotencyKey }) => {
            let result: PurchaseResult;

            try {
              result = await api.post<PurchaseResult>(
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
            } catch (error) {
              // Failed, timed out, or "being confirmed": the order list
              // must still reflect whatever the server did.
              void queryClient.invalidateQueries({ queryKey: ORDERS_KEY });
              throw error;
            }

            purchased.current = true;

            // Load the new order first so the number page never opens empty.
            await queryClient.invalidateQueries({ queryKey: ORDERS_KEY });

            const list = queryClient.getQueryData<Order[]>(ORDERS_KEY);
            const orderId =
              result.order_id ??
              list?.find((order) => order.reference === result.reference)?.id ??
              null;

            // Go straight to the number page. Not the transaction page.
            if (orderId) setViewingId(orderId);

            return result;
          }}
        />
      )}
    </div>
  );
}
