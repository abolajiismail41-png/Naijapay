import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Banner, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";

interface M { kobo: number; naira: string }
interface Block { transactions: number; transaction_volume: M; customer_paid: M; provider_cost: M; gross_revenue: M; gross_profit: M; discounts: M; referral_commissions: M; refunds_reversals_loss: M; net_contribution: M; gross_margin_pct: string; net_margin_pct: string }
interface Profit { period: { from: string; to: string }; totals: Block; groups?: Array<{ key: string } & Block>; not_in_profit: { failed_and_refunded_transactions: number; failed_and_refunded_value: M }; funding_fee_income: M; payment_processing_cost: null; payment_processing_cost_note: string }
interface Checks { all_ok: boolean; checks: Array<{ check: string; expected_kobo: number; actual_kobo: number; diff_kobo: number; ok: boolean }> }

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Lagos" });
const GROUPS = ["", "service", "provider", "network", "date", "disco", "product"];
const n = (m: M) => `₦${m.naira.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;

function Stat({ k, v, tone }: { k: string; v: string; tone?: "good" }) {
  return <div className="stat"><div className="muted xs">{k}</div><div className="v" style={tone ? { color: "var(--accent-strong)" } : undefined}>{v}</div></div>;
}

export default function ProfitPage() {
  const [from, setFrom] = useState(today()); const [to, setTo] = useState(today()); const [group, setGroup] = useState("");
  const q = useQuery({ queryKey: ["profit", from, to, group], queryFn: () => api.get<Profit>("/api/v1/admin/finance/profit", { from_date: from, to_date: to, group_by: group || undefined }) });
  const checks = useQuery({ queryKey: ["ledger-checks"], queryFn: () => api.get<Checks>("/api/v1/admin/finance/ledger-checks") });
  const t = q.data?.totals;
  return (
    <div className="stack">
      <div className="row" style={{ flexWrap: "wrap", alignItems: "end" }}>
        <div className="field"><label htmlFor="f">From</label><input id="f" className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div className="field"><label htmlFor="t">To</label><input id="t" className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <div className="field"><label htmlFor="g">Group by</label><select id="g" className="input" value={group} onChange={(e) => setGroup(e.target.value)}>{GROUPS.map((g) => <option key={g} value={g}>{g || "None"}</option>)}</select></div>
      </div>
      {q.isError && <Banner tone="error">{friendly(q.error)}</Banner>}
      {!t ? <Skeleton h={120} /> : (
        <>
          <div className="stat-grid">
            <Stat k={`Transactions`} v={String(t.transactions)} /><Stat k="Volume (gross revenue)" v={n(t.gross_revenue)} /><Stat k="Provider cost" v={n(t.provider_cost)} />
            <Stat k="Gross profit" v={n(t.gross_profit)} tone="good" /><Stat k="Discounts" v={n(t.discounts)} /><Stat k="Referral commissions" v={n(t.referral_commissions)} />
            <Stat k="Loss on reversals" v={n(t.refunds_reversals_loss)} /><Stat k="Net contribution" v={n(t.net_contribution)} tone="good" />
            <Stat k="Gross margin" v={`${t.gross_margin_pct}%`} /><Stat k="Net margin" v={`${t.net_margin_pct}%`} /><Stat k="Customers paid" v={n(t.customer_paid)} /><Stat k="Funding fee income" v={n(q.data!.funding_fee_income)} />
          </div>
          <p className="hint">Failed and refunded purchases ({q.data!.not_in_profit.failed_and_refunded_transactions}, {n(q.data!.not_in_profit.failed_and_refunded_value)}) are not sales and are excluded. {q.data!.payment_processing_cost_note}</p>
          {q.data!.groups && (
            <div className="card flush scroll-x"><table className="table"><thead><tr><th>{group}</th><th className="r">Txns</th><th className="r">Revenue</th><th className="r">Cost</th><th className="r">Gross profit</th><th className="r">Discounts</th><th className="r">Net</th><th className="r">Margin</th></tr></thead>
              <tbody>{q.data!.groups.map((g) => <tr key={g.key}><td>{g.key}</td><td className="r">{g.transactions}</td><td className="r">{n(g.gross_revenue)}</td><td className="r">{n(g.provider_cost)}</td><td className="r">{n(g.gross_profit)}</td><td className="r">{n(g.discounts)}</td><td className="r">{n(g.net_contribution)}</td><td className="r">{g.gross_margin_pct}%</td></tr>)}</tbody></table></div>
          )}
        </>
      )}
      <section className="stack-sm"><h2 className="section-title">Ledger integrity</h2>
        {checks.data ? (
          <div className="card flush scroll-x"><table className="table"><tbody>{checks.data.checks.map((c) => <tr key={c.check}><td>{c.check}</td><td className="r">{c.diff_kobo === 0 ? "matches" : `off by ${c.diff_kobo} kobo`}</td><td><span className={`badge ${c.ok ? "ok" : "bad"}`}>{c.ok ? "OK" : "CHECK"}</span></td></tr>)}</tbody></table></div>
        ) : checks.isError ? <Banner tone="error">{friendly(checks.error)}</Banner> : <Skeleton h={80} />}
      </section>
    </div>
  );
}
