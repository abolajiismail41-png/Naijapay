import { useQuery } from "@tanstack/react-query";
import { Banner, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";

interface Overview { as_of: string; timezone: string; users: { total: number; active: number; suspended: number; closed: number }; transactions: { total: number; created_today: number; pending: number; processing: number; unknown: number; failed: number; successful: number } }
function Stat({ label, value, alert = false }: { label: string; value: number; alert?: boolean }) {
  return <div className="stat"><div className="muted xs">{label}</div><div className="v" style={alert && value ? { color: "var(--danger)" } : undefined}>{value.toLocaleString()}</div></div>;
}
export default function Overview() {
  const q = useQuery({ queryKey: ["admin-overview"], queryFn: () => api.get<Overview>("/api/v1/admin/overview"), refetchInterval: 30_000 });
  if (q.isPending) return <Skeleton h={180} />;
  if (q.isError || !q.data) return <Banner tone="error">{friendly(q.error)}</Banner>;
  const d = q.data;
  return <div className="stack">
    <p className="muted small">Operational metrics only — financial totals and profit are restricted to the Finance dashboard. Refreshes every 30 seconds.</p>
    <section className="stack-sm"><h2 className="section-title">Customers</h2><div className="stat-grid"><Stat label="Total users" value={d.users.total}/><Stat label="Active" value={d.users.active}/><Stat label="Suspended" value={d.users.suspended} alert/><Stat label="Closed" value={d.users.closed}/></div></section>
    <section className="stack-sm"><h2 className="section-title">Transactions</h2><div className="stat-grid"><Stat label="All time" value={d.transactions.total}/><Stat label="Created today" value={d.transactions.created_today}/><Stat label="Pending" value={d.transactions.pending} alert/><Stat label="Processing" value={d.transactions.processing}/><Stat label="Unknown outcome" value={d.transactions.unknown} alert/><Stat label="Failed" value={d.transactions.failed}/><Stat label="Successful" value={d.transactions.successful}/></div></section>
    {(d.transactions.unknown > 0 || d.transactions.pending > 0) && <Banner tone="warn">Some transactions need monitoring. Use Transactions to investigate pending or unknown outcomes; never retry an unknown provider result blindly.</Banner>}
    <p className="muted xs">As of {new Date(d.as_of).toLocaleString("en-NG", { timeZone: d.timezone })} ({d.timezone}).</p>
  </div>;
}
