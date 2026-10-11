import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Chips, PhoneField, usePhone } from "../components/forms";
import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
import {
  Banner,
  Button,
  Empty,
  PageHead,
  Skeleton,
} from "../components/ui";
import { api, friendly } from "../lib/api";
import { formatKobo } from "../lib/money";
import { label } from "../lib/txn";
import type { DataPlan, Network, Txn } from "../lib/types";
import "../styles/data-plans.css";
const NETWORKS: Network[] = ["MTN", "AIRTEL", "GLO", "9MOBILE"];
const TABS = ["hot", "daily", "weekly", "monthly", "long"] as const;
type Tab = (typeof TABS)[number];
/**
 * These promotional fields are optional because they may not be
 * present in every API response.
 *
 * This local extension avoids changing the shared DataPlan type
 * or assuming that the backend always supplies promotional data.
 */
type DataPlanWithPromotions = DataPlan & {
  hot?: boolean;
  cashback_kobo?: number;
};
const TAB_TEXT: Record<Tab, string> = {
  hot: "Hot Deals",
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  long: "Long term",
};
/** Converts validity strings such as "1 Day", "2 Weeks" or "1 Month" to days. */
function validityDays(validity: string): number {
  const match = /(\d+)\s*(day|week|month|year)/i.exec(validity);
  if (!match) return 30;
  const amount = Number(match[1]);
  const unit = match[2].toLowerCase();
  switch (unit) {
    case "day":
      return amount;
    case "week":
      return amount * 7;
    case "month":
      return amount * 30;
    case "year":
      return amount * 365;
    default:
      return 30;
  }
}
function tabOf(plan: DataPlan): Exclude<Tab, "hot"> {
  const days = validityDays(plan.validity);
  if (days <= 2) return "daily";
  if (days <= 7) return "weekly";
  if (days <= 31) return "monthly";
  return "long";
}
function cashbackText(kobo: number): string {
  const naira = kobo / 100;
  return `₦${
    Number.isInteger(naira) ? naira : naira.toFixed(2)
  } cashback`;
}
export default function Data() {
  const { toast } = useToast();
  const [network, setNetwork] = useState<Network>("MTN");
  const [tab, setTab] = useState<Tab>("hot");
  const [planId, setPlanId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const phone = usePhone();
  const plans = useQuery({
    queryKey: ["data-plans", network],
    queryFn: () =>
      api.get<DataPlanWithPromotions[]>("/api/v1/data/plans", {
        network,
      }),
  });
  const allPlans = plans.data ?? [];
  const plan = allPlans.find((item) => item.id === planId) ?? null;
  const visible = useMemo(() => {
    if (tab === "hot") {
      const flagged = allPlans.filter((item) => item.hot === true);
      if (flagged.length > 0) {
        return flagged;
      }
      // Fallback when the API doesn't flag any Hot Deals.
      return [...allPlans]
        .sort((a, b) => a.price_kobo - b.price_kobo)
        .slice(0, 8);
    }
    return allPlans.filter((item) => tabOf(item) === tab);
  }, [allPlans, tab]);
  return (
    <div className="stack">
      <PageHead title="Buy Data" back="/pay" />
      <div className="stack-sm">
        <span className="section-title">Network</span>
        <Chips
          label="Network"
          value={network}
          onChange={(value) => {
            setNetwork(value as Network);
            setPlanId(null);
          }}
          options={NETWORKS.map((item) => ({
            key: item,
            text: label(item),
          }))}
        />
      </div>
      <section className="stack-sm">
        <span className="section-title">Select a data plan</span>
        <div
          className="plan-tabs"
          role="tablist"
          aria-label="Plan category"
        >
          {TABS.map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={tab === item}
              className="plan-tab"
              onClick={() => setTab(item)}
            >
              {item === "hot" && (
                <span aria-hidden="true">🔥 </span>
              )}
              {TAB_TEXT[item]}
            </button>
          ))}
        </div>
        {plans.isPending ? (
          <div className="plan-grid" aria-busy="true">
            {[0, 1, 2, 3, 4, 5].map((item) => (
              <Skeleton key={item} h={160} />
            ))}
          </div>
        ) : plans.isError ? (
          <Banner tone="error">
            {String(
              friendly(plans.error) || "Unable to load data plans.",
            )}
          </Banner>
        ) : visible.length === 0 ? (
          <div className="card">
            <Empty title="No plans here">
              There are no {label(network)}{" "}
              {TAB_TEXT[tab].toLowerCase()} plans right now.
            </Empty>
          </div>
        ) : (
          <div
            className="plan-grid"
            role="radiogroup"
            aria-label="Data plans"
          >
            {visible.map((item) => (
              <button
                key={item.id}
                type="button"
                role="radio"
                aria-checked={planId === item.id}
                className="plan-card"
                onClick={() => setPlanId(item.id)}
              >
                <span className="plan-top">
                  {typeof item.cashback_kobo === "number" &&
                    item.cashback_kobo > 0 && (
                      <span className="plan-badge">
                        {cashbackText(item.cashback_kobo)}
                      </span>
                    )}
                </span>
                <span className="plan-size">{item.name}</span>
                <span className="plan-price num">
                  {formatKobo(item.price_kobo)}
                </span>
                <span className="plan-meta">
                  <span className="plan-validity">
                    {item.validity} validity
                  </span>
                  {item.type && (
                    <span className="plan-desc">{item.type}</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
      <PhoneField
        raw={phone.raw}
        onChange={phone.setRaw}
        error={phone.error}
      />
      <Button
        block
        disabled={!plan || !phone.valid}
        onClick={() => setOpen(true)}
      >
        Review
      </Button>
      {plan && phone.e164 && (
        <ReviewSheet
          open={open}
          onClose={() => setOpen(false)}
          title="Review data purchase"
          lines={[
            ["Network", label(plan.network)],
            ["Plan", `${plan.name} · ${plan.validity}`],
            ["Number", phone.raw],
          ]}
          total={formatKobo(plan.price_kobo)}
          onPriceChanged={(message) => {
            toast(message);
            void plans.refetch();
          }}
          submit={({ pinToken, idempotencyKey, confirmNetwork }) =>
            api.post<Txn>(
              "/api/v1/data",
              {
                plan_id: plan.id,
                phone: phone.e164,
                confirmed_price_kobo: plan.price_kobo,
                confirm_network: confirmNetwork,
              },
              {
                pinToken,
                idempotencyKey,
              },
            )
          }
        />
      )}
    </div>
  );
}