import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { Banner, Button, KV, MoneyField, StatusBadge, TextField } from "../components/ui";
import { useToast } from "../components/Toast";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { parseNairaToKobo } from "../lib/money";
import { FINANCE_ROLES } from "../lib/types";

interface Detail {
  reference: string; service: string; status: string; display_status: string; message: string; price: string; network: string | null; user_id: string; provider_reference: string | null; failure_reason: string | null; created_at: string;
  events: Array<{ from: string | null; to: string; note: string; at: string }>;
  pricing?: Record<string, string | number | boolean | null>;
}

function Resolve({ d }: { d: Detail }) {
  const qc = useQueryClient(); const { toast } = useToast();
  const [outcome, setOutcome] = useState<"SUCCESS" | "FAILED">("FAILED"); const [note, setNote] = useState(""); const [cost, setCost] = useState(""); const [token, setToken] = useState(""); const [pins, setPins] = useState("");
  const m = useMutation({
    mutationFn: () => {
      const lines = pins.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(/[,\s]+/, 2) as [string, string]);
      return api.post(`/api/v1/admin/transactions/${d.reference}/resolve`, { outcome, note, provider_cost_kobo: outcome === "SUCCESS" && cost ? parseNairaToKobo(cost) ?? undefined : undefined, token: token || undefined, pins: lines.length ? lines.map(([a, b]) => [a, b ?? ""]) : undefined });
    },
    onSuccess: () => { toast("Resolved"); void qc.invalidateQueries({ queryKey: ["admin-txn"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  return (
    <section className="card stack"><h2>Resolve manually</h2>
      <Banner tone="warn">Only after confirming the real outcome on the provider's dashboard. FAILED refunds the customer; SUCCESS settles the sale. This cannot be undone.</Banner>
      <div className="seg"><button type="button" aria-pressed={outcome === "FAILED"} onClick={() => setOutcome("FAILED")}>Not delivered</button><button type="button" aria-pressed={outcome === "SUCCESS"} onClick={() => setOutcome("SUCCESS")}>Delivered</button></div>
      {outcome === "SUCCESS" && <>
        <MoneyField label="Actual provider cost" value={cost} onChange={setCost} />
        {d.service === "ELECTRICITY" && <TextField label="Token" value={token} onChange={setToken} />}
        {d.service === "EDUCATION" && <div className="field"><label htmlFor="pins">PINs (one per line: pin serial)</label><textarea id="pins" className="input" rows={3} value={pins} onChange={(e) => setPins(e.target.value)} /></div>}
      </>}
      <TextField label="Note (what you checked)" value={note} onChange={setNote} />
      <Button variant={outcome === "FAILED" ? "danger" : "primary"} loading={m.isPending} disabled={note.trim().length < 5} onClick={() => m.mutate()}>{outcome === "FAILED" ? "Refund customer" : "Mark delivered"}</Button>
    </section>
  );
}

export default function AdminTransactions() {
  const { me } = useAuth();
  const [input, setInput] = useState(""); const [ref, setRef] = useState("");
  const q = useQuery({ queryKey: ["admin-txn", ref], enabled: /^txn_[0-9a-f]{32}$/.test(ref), retry: false, queryFn: () => api.get<Detail>(`/api/v1/admin/transactions/${ref}`) });
  const d = q.data;
  function go(e: FormEvent) { e.preventDefault(); setRef(input.trim()); }
  return (
    <div className="stack">
      <form className="row" onSubmit={go} style={{ alignItems: "end" }}><div className="grow"><TextField label="Transaction reference" value={input} onChange={setInput} placeholder="txn_…" /></div><Button type="submit" disabled={!input.trim()}>Find</Button></form>
      {ref && !/^txn_[0-9a-f]{32}$/.test(ref) && <Banner tone="error">That does not look like a transaction reference.</Banner>}
      {q.isError && <Banner tone="error">{friendly(q.error)}</Banner>}
      {d && (
        <>
          <section className="card"><div className="row between"><h2>{d.service}</h2><StatusBadge status={d.display_status} /></div><dl style={{ margin: 0 }}>
            <KV k="Status" v={d.status} /><KV k="Customer paid" v={`₦${d.price}`} /><KV k="User" v={<span className="mono xs">{d.user_id}</span>} /><KV k="Provider ref" v={d.provider_reference ?? "none"} /><KV k="Created" v={fmtDateTime(d.created_at)} />{d.failure_reason && <KV k="Failure" v={d.failure_reason} />}</dl></section>
          {d.pricing && me && FINANCE_ROLES.includes(me.role) && <section className="card"><h2>Pricing snapshot</h2><dl style={{ margin: 0 }}>{Object.entries(d.pricing).map(([k, v]) => <KV key={k} k={k.replaceAll("_", " ")} v={String(v)} />)}</dl></section>}
          <section className="card"><h2>Timeline</h2><ol className="stack-sm" style={{ paddingLeft: 18, margin: "8px 0 0" }}>{d.events.map((e, i) => <li key={i}><strong>{e.to}</strong> <span className="muted small">{fmtDateTime(e.at)}{e.note ? ` · ${e.note}` : ""}</span></li>)}</ol></section>
          {["UNKNOWN", "PROCESSING"].includes(d.status) && me && FINANCE_ROLES.includes(me.role) && <Resolve d={d} />}
        </>
      )}
    </div>
  );
}
