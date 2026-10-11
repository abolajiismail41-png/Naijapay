import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { Banner, Button, Skeleton, TextField } from "../components/ui";
import { useToast } from "../components/Toast";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";

interface FraudCase { id: string; transaction_id: string; user_id: string; rule_code: string; severity: string; score: number; status: string; reasons: Array<Record<string, unknown>>; resolution_note: string | null; created_at: string }
interface FraudPage { items: FraudCase[] }
interface ReconRun { id: string; run_type: string; status: string; started_at: string; finished_at: string | null; summary: { issue_count?: number; checks?: Array<{ code: string; ok: boolean; sample_count?: number; difference_kobo?: number }>; note?: string } }
interface ReconPage { items: ReconRun[] }

export default function RiskOperations() {
  const { me } = useAuth(); const qc = useQueryClient(); const { toast } = useToast();
  const [note, setNote] = useState<Record<string, string>>({});
  const fraudAllowed = me && ["ADMIN", "SUPER_ADMIN"].includes(me.role);
  const reconAllowed = me && ["FINANCE", "SUPER_ADMIN"].includes(me.role);
  const fraud = useQuery({ queryKey: ["fraud-cases"], enabled: !!fraudAllowed, queryFn: () => api.get<FraudPage>("/api/v1/admin/fraud", { limit: 50 }) });
  const runs = useQuery({ queryKey: ["reconciliation-runs"], enabled: !!reconAllowed, queryFn: () => api.get<ReconPage>("/api/v1/admin/reconciliation", { limit: 30 }) });
  const resolve = useMutation({ mutationFn: ({ id, status }: { id: string; status: "REVIEWING" | "CLEARED" | "CONFIRMED" }) => api.patch(`/api/v1/admin/fraud/${id}`, { status, note: note[id]?.trim() || "Reviewed using available transaction evidence." }), onSuccess: () => { toast("Fraud case updated"); void qc.invalidateQueries({ queryKey: ["fraud-cases"] }); }, onError: e => toast(friendly(e), "error") });
  const run = useMutation({ mutationFn: () => api.post<ReconRun>("/api/v1/admin/reconciliation/run"), onSuccess: () => { toast("Reconciliation finished"); void qc.invalidateQueries({ queryKey: ["reconciliation-runs"] }); }, onError: e => toast(friendly(e), "error") });
  return <div className="stack">
    {fraudAllowed && <section className="stack"><div><h2>Fraud review queue</h2><p className="muted small">Rules create investigation signals only. They do not automatically block customers or move money.</p></div>
      {fraud.isError && <Banner tone="error">{friendly(fraud.error)}</Banner>}
      {fraud.isPending ? <Skeleton h={150} /> : fraud.data?.items.length ? fraud.data.items.map(c => <article className="card stack-sm" key={c.id}>
        <div className="row between" style={{ alignItems: "start" }}><div><strong>{c.rule_code.replaceAll("_", " ")}</strong><div className="muted xs">{fmtDateTime(c.created_at)}</div></div><span className={`badge ${c.severity === "HIGH" || c.severity === "CRITICAL" ? "bad" : c.severity === "MEDIUM" ? "wait" : "neutral"}`}>{c.severity} · {c.score}/100</span></div>
        <dl style={{ margin: 0 }}><div className="kv"><dt>Transaction</dt><dd className="mono xs">{c.transaction_id}</dd></div><div className="kv"><dt>Customer</dt><dd className="mono xs">{c.user_id}</dd></div><div className="kv"><dt>Status</dt><dd>{c.status}</dd></div></dl>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: "var(--t-xs)" }}>{JSON.stringify(c.reasons, null, 2)}</pre>
        {!["CLEARED", "CONFIRMED"].includes(c.status) && <><TextField label="Review note" value={note[c.id] ?? ""} onChange={v => setNote(old => ({ ...old, [c.id]: v }))} placeholder="Evidence checked and conclusion" /><div className="row" style={{ flexWrap: "wrap" }}><Button sm variant="secondary" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: c.id, status: "REVIEWING" })}>Mark reviewing</Button><Button sm variant="secondary" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: c.id, status: "CLEARED" })}>Clear alert</Button><Button sm variant="danger" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: c.id, status: "CONFIRMED" })}>Confirm fraud</Button></div></>}
        {c.resolution_note && <p className="muted small">Resolution: {c.resolution_note}</p>}
      </article>) : <div className="card empty">No fraud cases found. Screening runs every five minutes.</div>}</section>}
    {reconAllowed && <section className="stack"><div className="row between" style={{ alignItems: "start" }}><div><h2>Reconciliation</h2><p className="muted small">Internal ledger integrity and transaction journal references. This does not match external bank or provider statements.</p></div><Button loading={run.isPending} onClick={() => run.mutate()}>Run checks now</Button></div>
      {run.isError && <Banner tone="error">{friendly(run.error)}</Banner>}{runs.isError && <Banner tone="error">{friendly(runs.error)}</Banner>}
      {runs.isPending ? <Skeleton h={150} /> : runs.data?.items.length ? runs.data.items.map(r => <article className="card stack-sm" key={r.id}><div className="row between"><strong>{r.run_type.replaceAll("_", " ")}</strong><span className={`badge ${r.status === "CLEAN" ? "success" : r.status === "ISSUES" ? "danger" : "neutral"}`}>{r.status}</span></div><div className="muted xs">{fmtDateTime(r.started_at)}</div><p>{r.summary.issue_count ?? 0} recorded issue(s)</p>{r.summary.checks?.map(c => <div className="row between" key={c.code}><span>{c.code.replaceAll("_", " ")}</span><span className={`badge ${c.ok ? "ok" : "bad"}`}>{c.ok ? "OK" : `ISSUE${c.sample_count ? ` · ${c.sample_count}` : ""}`}{c.difference_kobo ? ` · ${c.difference_kobo} kobo` : ""}</span></div>)}{r.summary.note && <p className="muted xs">{r.summary.note}</p>}</article>) : <div className="card empty">No reconciliation runs yet. Run the first internal check above.</div>}</section>}
    {!fraudAllowed && !reconAllowed && <Banner tone="warn">Your role does not have access to fraud review or reconciliation.</Banner>}
  </div>;
}
