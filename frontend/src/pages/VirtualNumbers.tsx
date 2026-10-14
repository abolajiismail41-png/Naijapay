import { useMemo, useState } from "react";
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

const SERVICE_SEARCH_MIN_LENGTH = 2;
const MAX_SERVICE_RESULTS = 100;

// Calls that wait on the SMS-Man API (price lookups, purchase, SMS check,
// cancel) can take far longer than the client's 20s default, so they use the
// slow-request timeout. Everything else keeps the default.
const SLOW = { timeoutMs: SLOW_REQUEST_TIMEOUT_MS };

function normaliseStatus(status: string): string {
  return status.trim().toUpperCase();
}

function availabilityLabel(price: Price | undefined): string {
  if (!price) return "No price for this country";

  if (price.available === true) {
    return price.inventory == null
      ? "Available"
      : `${price.inventory.toLocaleString()} available`;
  }

  if (price.available === false) {
    return "Currently unavailable";
  }

  return "Availability unknown";
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

export default function VirtualNumbers() {
  const [countryId, setCountryId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [search, setSearch] = useState("");
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
    enabled: countryId !== "",
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

  const filteredServices = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (query.length < SERVICE_SEARCH_MIN_LENGTH) {
      return [];
    }

    return (services.data ?? [])
      .filter(
        (service) =>
          service.name.toLowerCase().includes(query) ||
          (service.code ?? "").toLowerCase().includes(query),
      )
      .slice(0, MAX_SERVICE_RESULTS);
  }, [services.data, search]);

  const selected = useMemo(
    () =>
      prices.data?.find(
        (price) => String(price.application_id) === serviceId,
      ),
    [prices.data, serviceId],
  );

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
          ? "SMS received"
          : "No SMS received yet",
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

  return (
    <div className="stack">
      <PageHead
        title="Virtual Numbers"
        sub="Buy a number for supported SMS verification services."
        back="/pay"
      />

      {globalError && (
        <Banner tone="error">{friendly(globalError)}</Banner>
      )}

      <section className="card stack-sm">
        <h2 className="section-title">Find a number</h2>

        <label className="field">
          <span>Country</span>

          <select
            className="input"
            value={countryId}
            disabled={countries.isPending}
            onChange={(event) => {
              setCountryId(event.target.value);
              setServiceId("");
              setReview(false);
            }}
          >
            <option value="">Choose a country</option>

            {(countries.data ?? []).map((country) => (
              <option key={country.id} value={String(country.id)}>
                {country.name}
              </option>
            ))}
          </select>
        </label>

        {countries.isPending && (
          <div className="stack">
            <Skeleton h={44} />
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
              Retry countries
            </Button>
          </div>
        )}

        <label className="field">
          <span>Search verification service</span>

          <input
            className="input"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setServiceId("");
              setReview(false);
            }}
            placeholder="e.g. Telegram, WhatsApp"
          />
        </label>

        {services.isPending && (
          <div className="stack">
            <Skeleton h={44} />
            <Skeleton h={44} />
          </div>
        )}

        {services.isError && (
          <div className="stack-sm">
            <p className="muted small">
              The service catalogue could not be loaded.
            </p>

            <Button
              variant="secondary"
              onClick={() => void services.refetch()}
            >
              Retry services
            </Button>
          </div>
        )}

        {!services.isPending && !services.isError && (
          <>
            <p className="muted small">
              {(services.data ?? []).length.toLocaleString()} services
              in the catalogue. Search by service name or code.
            </p>

            {search.trim().length < SERVICE_SEARCH_MIN_LENGTH ? (
              <Empty title="Search for a service">
                Enter at least two characters to find a verification
                service.
              </Empty>
            ) : filteredServices.length === 0 ? (
              <Empty title="No matching services">
                Try another name or service code.
              </Empty>
            ) : (
              <div className="stack-sm">
                {countryId === "" && (
                  <p className="muted small">
                    Choose a country to see prices and availability.
                  </p>
                )}

                {countryId !== "" && prices.isPending && (
                  <div className="stack">
                    <p className="muted small">
                      Loading live prices from the provider. This can
                      take up to a minute.
                    </p>
                    <Skeleton h={44} />
                    <Skeleton h={44} />
                  </div>
                )}

                {countryId !== "" && prices.isError && (
                  <div className="stack-sm">
                    <Banner tone="error">
                      {friendly(prices.error)}
                    </Banner>

                    <Button
                      variant="secondary"
                      onClick={() => void prices.refetch()}
                    >
                      Retry prices
                    </Button>
                  </div>
                )}

                {filteredServices.map((service) => {
                  const price = prices.data?.find(
                    (item) =>
                      String(item.application_id) ===
                      String(service.id),
                  );

                  const purchasable = isPurchasable(price);
                  const isSelected =
                    serviceId === String(service.id);

                  return (
                    <button
                      type="button"
                      key={service.id}
                      className="list-row"
                      disabled={
                        countryId !== "" &&
                        !prices.isPending &&
                        !prices.isError &&
                        !purchasable
                      }
                      style={{
                        width: "100%",
                        textAlign: "left",
                        background: isSelected
                          ? "var(--surface-2, var(--surface))"
                          : "transparent",
                        border: 0,
                        cursor: purchasable
                          ? "pointer"
                          : "not-allowed",
                        opacity:
                          countryId === "" ||
                          prices.isPending ||
                          purchasable
                            ? 1
                            : 0.65,
                      }}
                      onClick={() => {
                        if (!purchasable) return;

                        setServiceId(String(service.id));
                        setReview(false);
                      }}
                    >
                      <span className="grow">
                        <span className="title">
                          {service.name}
                        </span>

                        <span
                          className="muted xs"
                          style={{ display: "block" }}
                        >
                          {countryId === ""
                            ? "Choose a country for pricing"
                            : prices.isPending
                              ? "Loading price…"
                              : prices.isError
                                ? "Price unavailable"
                                : availabilityLabel(price)}
                        </span>
                      </span>

                      <span className="num">
                        {countryId === ""
                          ? "—"
                          : prices.isPending
                            ? "…"
                            : price
                              ? formatKobo(price.price_kobo)
                              : "—"}
                      </span>
                    </button>
                  );
                })}

                {filteredServices.length === MAX_SERVICE_RESULTS && (
                  <p className="muted small">
                    Showing the first {MAX_SERVICE_RESULTS} matches.
                    Refine your search to find other services.
                  </p>
                )}
              </div>
            )}
          </>
        )}

        {selected && (
          <div className="card stack-sm">
            <div className="row between">
              <span>Country</span>
              <strong>{selected.country_name}</strong>
            </div>

            <div className="row between">
              <span>Service</span>
              <strong>{selected.service_name}</strong>
            </div>

            <div className="row between">
              <span>Availability</span>
              <strong>{availabilityLabel(selected)}</strong>
            </div>

            <div className="row between">
              <span>Price</span>
              <strong className="num">
                {formatKobo(selected.price_kobo)}
              </strong>
            </div>

            <p className="muted small">
              The live provider price is checked again before your
              wallet is charged. Buying can take up to a minute; please
              keep this page open.
            </p>

            <Button
              block
              disabled={!isPurchasable(selected)}
              onClick={() => setReview(true)}
            >
              Review purchase
            </Button>
          </div>
        )}
      </section>

      {selected && (
        <ReviewSheet
          open={review}
          onClose={() => setReview(false)}
          title="Review virtual number"
          lines={[
            ["Country", selected.country_name],
            ["Service", selected.service_name],
            ["Number", "Assigned after purchase"],
          ]}
          total={formatKobo(selected.price_kobo)}
          note="The backend checks the live provider price before purchase. If the provider outcome is uncertain, the order stays under confirmation and must not be retried."
          onPriceChanged={(message) => {
            toast(message);
            void prices.refetch();
          }}
          submit={async ({ pinToken, idempotencyKey }) => {
            try {
              return await api.post<Txn>(
                "/api/v1/virtual-numbers/orders",
                {
                  country_id: selected.country_id,
                  application_id: selected.application_id,
                  confirmed_price_kobo: selected.price_kobo,
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

      {smsCode && (
        <div className="card stack-sm">
          <h2 className="section-title">
            Received verification code
          </h2>

          <strong
            className="num"
            style={{ fontSize: "var(--t-xl)" }}
          >
            {smsCode}
          </strong>

          <Button
            variant="secondary"
            onClick={() => {
              void navigator.clipboard
                .writeText(smsCode)
                .then(() => toast("Code copied"))
                .catch(() => toast("Could not copy code"));
            }}
          >
            Copy code
          </Button>
        </div>
      )}

      <section className="stack-sm">
        <h2 className="section-title">My Virtual Numbers</h2>

        {orders.isPending ? (
          <div className="stack">
            <Skeleton h={72} />
            <Skeleton h={72} />
          </div>
        ) : orders.isError ? (
          <div className="stack-sm">
            <p className="muted small">
              Your virtual number orders could not be loaded.
            </p>

            <Button
              variant="secondary"
              onClick={() => void orders.refetch()}
            >
              Retry orders
            </Button>
          </div>
        ) : !orders.data?.length ? (
          <Empty title="No virtual number orders yet" />
        ) : (
          <div className="card flush list">
            {orders.data.map((order) => {
              const status = normaliseStatus(order.status);
              const active =
                status === "ACTIVE" ||
                status === "SMS_RECEIVED";
              const uncertain =
                status === "UNKNOWN" || status === "PENDING";
              const canCheckSms =
                Boolean(order.phone_number) && active;
              const canCancel =
                Boolean(order.phone_number) &&
                ["ACTIVE", "SMS_RECEIVED"].includes(status);

              return (
                <div className="list-row" key={order.id}>
                  <div className="grow stack-sm">
                    <div className="row between">
                      <strong>
                        {order.phone_number ?? order.service_name}
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
                      {order.country_name} · {order.service_name} ·{" "}
                      {new Date(order.created_at).toLocaleString()}
                    </span>

                    <strong className="num">
                      {formatKobo(order.price_kobo)}
                    </strong>

                    {order.failure_reason && (
                      <span className="small">
                        {order.failure_reason}
                      </span>
                    )}

                    {order.sms_code && (
                      <div className="banner info">
                        Verification code:{" "}
                        <strong>{order.sms_code}</strong>
                      </div>
                    )}

                    {uncertain && (
                      <span className="muted small">
                        We are confirming this order with the
                        provider. Do not retry the purchase.
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
                        The order is cancelled. Refund eligibility
                        depends on the confirmed provider outcome.
                      </span>
                    )}
                  </div>

                  <div className="stack-sm">
                    {canCheckSms && (
                      <Button
                        sm
                        variant="secondary"
                        loading={smsMutation.isPending}
                        disabled={smsMutation.isPending}
                        onClick={() => {
                          setSmsCode(null);
                          smsMutation.mutate(order.id);
                        }}
                      >
                        Check SMS
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
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}