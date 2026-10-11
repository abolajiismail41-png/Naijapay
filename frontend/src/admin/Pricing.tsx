import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Banner, Button, KV, MoneyField, Skeleton, TextField } from "../components/ui";
import { useToast } from "../components/Toast";
import { api, friendly } from "../lib/api";
import { formatKobo, parseNairaToKobo } from "../lib/money";
import { buildPricing, emptyP, PricingFields } from "./PricingFields";

interface Rule { id: string; category: string; scope_key: string | null; provider_code: string | null; method: string; markup_percent: string | null; markup_kobo: number | null; custom_price_kobo: number | null; fee_kobo: number; discount_bps: number; discount_kobo: number; rounding_kobo: number; cap_at_face: boolean; allow_subsidy: boolean; version: number; note: string; created_at: string }
interface Cost { provider: string; category: string; scope: string; provider_service_id: string; kind: string; value: number; source: string; synced_at: string | null }
const CATEGORIES = ["AIRTIME", "DATA", "ELECTRICITY", "EDUCATION", "TV"];

function Preview() {
  const [s, setS] = useState(emptyP()); const [cost, setCost] = useState("975"); const [face, setFace] = useState("");
  const m = useMutation({ mutationFn: (body: unknown) => api.post<Record<string, string | boolean | null>>("/api/v1/admin/pricing/preview", body) });
  function run() {
    const b = buildPricing(s); const c = parseNairaToKobo(cost);
    if ("error" in b || c === null || c <= 0) return;
    const f = parseNairaToKobo(face);
    m.mutate({ ...b.body, provider_cost_kobo: c, face_value_kobo: f && f > 0 ? f : undefined });
  }
  const r = m.data; const built = buildPricing(s);
  return (
    <section className="card stack"><h2>Price calculator</h2>
      <MoneyField label="Provider cost" value={cost} onChange={setCost} />
      <MoneyField label="Face value (airtime / electricity / FACE_VALUE)" value={face} onChange={setFace} />
      <PricingFields s={s} set={setS} />
      {"error" in built && <p className="field-error">{built.error}</p>}
      <Button onClick={run} loading={m.isPending} disabled={"error" in built}>Calculate</Button>
      {m.isError && <Banner tone="error">{friendly(m.error)}</Banner>}
      {r && (<><dl style={{ margin: 0 }}><KV k="Customer price" v={`₦${r.customer_price}`} /><KV k="Markup" v={`₦${r.markup}`} /><KV k="Fee" v={`₦${r.fee}`} /><KV k="Discount" v={`₦${r.discount}`} /><KV k="Gross profit" v={`₦${r.gross_profit}`} /><KV k="Margin" v={`${r.margin_pct}%`} /><KV k="Net contribution" v={`₦${r.net_contribution}`} /></dl>
        {r.blocked ? <Banner tone="error">{String(r.block_reason)} New sales would be blocked.</Banner> : null}
        {r.capped_to_face_value ? <Banner tone="info">Price capped at face value.</Banner> : null}</>)}
    </section>
  );
}

function NewRule() {
  const qc = useQueryClient(); const { toast } = useToast();
  const [category, setCategory] = useState("AIRTIME"); const [scope, setScope] = useState(""); const [note, setNote] = useState(""); const [s, setS] = useState(emptyP());
  const built = buildPricing(s);
  const m = useMutation({
    mutationFn: (body: unknown) => api.post("/api/v1/admin/pricing/rules", body),
    onSuccess: () => { toast("Rule saved: it applies to new transactions only"); void qc.invalidateQueries({ queryKey: ["rules"] }); setNote(""); },
    onError: (e) => toast(friendly(e), "error"),
  });
  return (
    <section className="card stack"><h2>New pricing rule</h2>
      <div className="field"><label htmlFor="rc">Service</label><select id="rc" className="input" value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></div>
      <TextField label="Scope (optional)" value={scope} onChange={setScope} hint="Airtime: network, e.g. MTN. Data: PLAN:<id>, MTN:SME or MTN. Electricity: IKEJA:PREPAID or IKEJA. Exams: PRODUCT:<id> or WAEC. Blank = default for the service." />
      <PricingFields s={s} set={setS} />
      <TextField label="Reason for this change" value={note} onChange={setNote} />
      {"error" in built && <p className="field-error">{built.error}</p>}
      <Button loading={m.isPending} disabled={"error" in built || note.trim().length < 3}
        onClick={() => "body" in built && m.mutate({ ...built.body, category, scope_key: scope.trim() || undefined, note: note.trim() })}>Save rule</Button>
    </section>
  );
}

export default function PricingPage() {
  const qc = useQueryClient(); const { toast } = useToast();
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api.get<Rule[]>("/api/v1/admin/pricing/rules") });
  const costs = useQuery({ queryKey: ["costs"], queryFn: () => api.get<Cost[]>("/api/v1/admin/pricing/costs") });
  const sync = useMutation({
    mutationFn: () => api.post("/api/v1/admin/pricing/costs/sync"),
    onSuccess: () => { toast("Provider costs synced"); void qc.invalidateQueries({ queryKey: ["costs"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  const desc = (r: Rule) => r.method === "PERCENT_MARKUP" ? `${r.markup_percent}% markup` : r.method === "FIXED_MARKUP" ? `${formatKobo(r.markup_kobo ?? 0)} markup` : r.method === "CUSTOM_PRICE" ? `${formatKobo(r.custom_price_kobo ?? 0)} fixed price` : "face value";
  return (
    <div className="stack">
      <Preview />
      <NewRule />
      <section className="stack-sm"><h2 className="section-title">Active rules</h2>
        {rules.isPending ? <Skeleton h={80} /> : rules.isError ? <Banner tone="error">{friendly(rules.error)}</Banner> :
          <div className="card flush scroll-x"><table className="table"><thead><tr><th>Service</th><th>Scope</th><th>Pricing</th><th className="r">Fee</th><th>Ver.</th><th>Note</th></tr></thead>
            <tbody>{rules.data.map((r) => <tr key={r.id}><td>{r.category}</td><td>{r.scope_key ?? "default"}</td><td>{desc(r)}{r.cap_at_face ? " · capped" : ""}{r.allow_subsidy ? " · SUBSIDY" : ""}</td><td className="r">{formatKobo(r.fee_kobo)}</td><td>{r.version}</td><td>{r.note}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="stack-sm"><div className="row between"><h2 className="section-title">Provider costs</h2><Button variant="secondary" sm loading={sync.isPending} onClick={() => sync.mutate()}>Sync from provider</Button></div>
        {costs.isPending ? <Skeleton h={80} /> : costs.isError ? <Banner tone="error">{friendly(costs.error)}</Banner> :
          <div className="card flush scroll-x"><table className="table"><thead><tr><th>Service</th><th>Item</th><th className="r">Cost</th><th>Source</th><th>Synced</th></tr></thead>
            <tbody>{costs.data.map((c) => <tr key={`${c.category}${c.provider_service_id}`}><td>{c.category}</td><td>{c.scope}</td><td className="r">{c.kind === "DISCOUNT_BPS" ? `${(c.value / 100).toFixed(2)}% off` : formatKobo(c.value)}</td><td>{c.source}</td><td>{c.synced_at ? new Date(c.synced_at).toLocaleString("en-NG") : "never"}</td></tr>)}</tbody></table></div>}
      </section>
    </div>
  );
}
