import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Banner, Button, MoneyField, Skeleton, TextField } from "../components/ui";
import { useToast } from "../components/Toast";
import { api, friendly } from "../lib/api";
import { parseNairaToKobo, parseScaled } from "../lib/money";

interface Plan { id: string; network: string; name: string; type: string; validity: string; listed: boolean; active: boolean; cost: string | null; customer_price: string | null; margin_pct: string | null; price_blocked: boolean }
interface Disco { id: string; code: string; name: string; listed: boolean; active: boolean; types: Record<string, { service_id: string; discount_bps: number | null; sample_customer_price: string | null; sample_margin_pct: string | null; price_blocked: boolean }> }
interface Product { id: string; code: string; name: string; listed: boolean; active: boolean; unit_cost: string | null; unit_price: string | null; unit_margin_pct: string | null; price_blocked: boolean }

function useToggle(base: string, key: string) {
  const qc = useQueryClient(); const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, listed }: { id: string; listed: boolean }) => api.patch(`${base}/${id}`, { listed }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [key] }),
    onError: (e) => toast(friendly(e), "error"),
  });
}
function ListedButton({ listed, busy, onClick }: { listed: boolean; busy: boolean; onClick: () => void }) {
  return <Button sm variant={listed ? "primary" : "secondary"} loading={busy} onClick={onClick} aria-pressed={listed}>{listed ? "Listed" : "Hidden"}</Button>;
}

function DataPlans() {
  const qc = useQueryClient(); const { toast } = useToast();
  const q = useQuery({ queryKey: ["admin-plans"], queryFn: () => api.get<Plan[]>("/api/v1/admin/data-plans") });
  const toggle = useToggle("/api/v1/admin/data-plans", "admin-plans");
  const sync = useMutation({ mutationFn: () => api.post("/api/v1/admin/pricing/costs/sync"), onSuccess: () => { toast("Synced"); void qc.invalidateQueries({ queryKey: ["admin-plans"] }); }, onError: (e) => toast(friendly(e), "error") });
  return (
    <div className="stack"><div className="row between"><p className="muted small">New plans arrive hidden. Review the price, then list them.</p><Button sm variant="secondary" loading={sync.isPending} onClick={() => sync.mutate()}>Sync plans</Button></div>
      {q.isPending ? <Skeleton h={100} /> : q.isError ? <Banner tone="error">{friendly(q.error)}</Banner> :
        <div className="card flush scroll-x"><table className="table"><thead><tr><th>Network</th><th>Plan</th><th className="r">Cost</th><th className="r">Price</th><th className="r">Margin</th><th></th></tr></thead>
          <tbody>{q.data.map((p) => <tr key={p.id}><td>{p.network}</td><td>{p.name} <span className="muted xs">{p.validity} {p.type}</span>{!p.active && <span className="badge bad">removed</span>}</td><td className="r">{p.cost ? `₦${p.cost}` : "—"}</td><td className="r">{p.price_blocked ? "blocked" : p.customer_price ? `₦${p.customer_price}` : "—"}</td><td className="r">{p.margin_pct ? `${p.margin_pct}%` : "—"}</td>
            <td><ListedButton listed={p.listed} busy={toggle.isPending && toggle.variables?.id === p.id} onClick={() => toggle.mutate({ id: p.id, listed: !p.listed })} /></td></tr>)}</tbody></table></div>}
    </div>
  );
}

function Discos() {
  const qc = useQueryClient(); const { toast } = useToast();
  const q = useQuery({ queryKey: ["admin-discos"], queryFn: () => api.get<Disco[]>("/api/v1/admin/electricity/discos") });
  const toggle = useToggle("/api/v1/admin/electricity/discos", "admin-discos");
  const sync = useMutation({ mutationFn: () => api.post("/api/v1/admin/electricity/sync"), onSuccess: () => { toast("Synced"); void qc.invalidateQueries({ queryKey: ["admin-discos"] }); }, onError: (e) => toast(friendly(e), "error") });
  const [f, setF] = useState({ code: "", name: "", pcode: "", pre: "", post: "", preD: "", postD: "" });
  const create = useMutation({
    mutationFn: () => api.post("/api/v1/admin/electricity/discos", {
      code: f.code.toUpperCase(), name: f.name, provider_disco_code: f.pcode,
      prepaid_service_id: f.pre || undefined, postpaid_service_id: f.post || undefined,
      prepaid_discount_bps: f.preD ? parseScaled(f.preD, 2) ?? undefined : undefined, postpaid_discount_bps: f.postD ? parseScaled(f.postD, 2) ?? undefined : undefined }),
    onSuccess: () => { toast("Disco added (hidden until you list it)"); setF({ code: "", name: "", pcode: "", pre: "", post: "", preD: "", postD: "" }); void qc.invalidateQueries({ queryKey: ["admin-discos"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  return (
    <div className="stack"><div className="row between"><p className="muted small">The provider mapping is editable because the live adapter is not yet verified.</p><Button sm variant="secondary" loading={sync.isPending} onClick={() => sync.mutate()}>Sync</Button></div>
      {q.isPending ? <Skeleton h={100} /> : q.isError ? <Banner tone="error">{friendly(q.error)}</Banner> :
        <div className="card flush scroll-x"><table className="table"><thead><tr><th>Disco</th><th>Types (sample ₦5,000 price / margin)</th><th></th></tr></thead>
          <tbody>{q.data.map((d) => <tr key={d.id}><td>{d.name}<div className="muted xs">{d.code}</div></td><td>{Object.entries(d.types).map(([t, v]) => <div key={t}>{t.toLowerCase()}: {v.price_blocked ? "blocked" : v.sample_customer_price ? `₦${v.sample_customer_price} / ${v.sample_margin_pct}%` : "no cost set"} <span className="muted xs">({v.service_id}{v.discount_bps !== null ? `, ${(v.discount_bps / 100).toFixed(2)}% off` : ""})</span></div>)}</td>
            <td><ListedButton listed={d.listed} busy={toggle.isPending && toggle.variables?.id === d.id} onClick={() => toggle.mutate({ id: d.id, listed: !d.listed })} /></td></tr>)}</tbody></table></div>}
      <details className="card"><summary><strong>Add a disco by hand</strong></summary><div className="stack" style={{ marginTop: 12 }}>
        <TextField label="Code (e.g. IKEJA)" value={f.code} onChange={set("code")} /><TextField label="Name" value={f.name} onChange={set("name")} /><TextField label="Provider's disco code" value={f.pcode} onChange={set("pcode")} />
        <div className="row"><div className="grow"><TextField label="Prepaid service id" value={f.pre} onChange={set("pre")} /></div><div className="grow"><TextField label="Discount %" value={f.preD} onChange={set("preD")} inputMode="decimal" /></div></div>
        <div className="row"><div className="grow"><TextField label="Postpaid service id" value={f.post} onChange={set("post")} /></div><div className="grow"><TextField label="Discount %" value={f.postD} onChange={set("postD")} inputMode="decimal" /></div></div>
        <Button loading={create.isPending} disabled={!f.code || !f.name || !f.pcode} onClick={() => create.mutate()}>Add disco</Button></div></details>
    </div>
  );
}

function Exams() {
  const qc = useQueryClient(); const { toast } = useToast();
  const q = useQuery({ queryKey: ["admin-products"], queryFn: () => api.get<Product[]>("/api/v1/admin/education/products") });
  const toggle = useToggle("/api/v1/admin/education/products", "admin-products");
  const [f, setF] = useState({ code: "", name: "", sid: "", cost: "" });
  const cost = parseNairaToKobo(f.cost);
  const create = useMutation({
    mutationFn: () => api.post("/api/v1/admin/education/products", { code: f.code.toUpperCase(), name: f.name, provider_service_id: f.sid, cost_kobo: cost }),
    onSuccess: () => { toast("Product added (hidden until you list it)"); setF({ code: "", name: "", sid: "", cost: "" }); void qc.invalidateQueries({ queryKey: ["admin-products"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  return (
    <div className="stack">
      {q.isPending ? <Skeleton h={100} /> : q.isError ? <Banner tone="error">{friendly(q.error)}</Banner> :
        <div className="card flush scroll-x"><table className="table"><thead><tr><th>Product</th><th className="r">Cost</th><th className="r">Price</th><th className="r">Margin</th><th></th></tr></thead>
          <tbody>{q.data.map((p) => <tr key={p.id}><td>{p.name}<div className="muted xs">{p.code}</div></td><td className="r">{p.unit_cost ? `₦${p.unit_cost}` : "—"}</td><td className="r">{p.price_blocked ? "blocked" : p.unit_price ? `₦${p.unit_price}` : "—"}</td><td className="r">{p.unit_margin_pct ? `${p.unit_margin_pct}%` : "—"}</td>
            <td><ListedButton listed={p.listed} busy={toggle.isPending && toggle.variables?.id === p.id} onClick={() => toggle.mutate({ id: p.id, listed: !p.listed })} /></td></tr>)}</tbody></table></div>}
      <details className="card"><summary><strong>Add a product</strong></summary><div className="stack" style={{ marginTop: 12 }}>
        <TextField label="Code (WAEC, NECO)" value={f.code} onChange={(v) => setF({ ...f, code: v })} /><TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} />
        <TextField label="Provider service id" value={f.sid} onChange={(v) => setF({ ...f, sid: v })} /><MoneyField label="Provider cost per PIN" value={f.cost} onChange={(v) => setF({ ...f, cost: v })} />
        <Button loading={create.isPending} disabled={!f.code || !f.name || !f.sid || !cost} onClick={() => create.mutate()}>Add product</Button></div></details>
    </div>
  );
}


interface TVProduct { id: string; operator_code: string; operator_name: string; provider_operator_id: string; provider_service_id: string; name: string; listed: boolean; active: boolean; unit_cost: string | null; unit_price: string | null; price_blocked: boolean }

function TVPackages() {
  const qc = useQueryClient(); const { toast } = useToast();
  const q = useQuery({ queryKey: ["admin-tv-products"], queryFn: () => api.get<TVProduct[]>("/api/v1/admin/tv/products") });
  const toggle = useToggle("/api/v1/admin/tv/products", "admin-tv-products");
  const [f, setF] = useState({ operatorCode: "", operatorName: "", operatorId: "", serviceId: "", name: "", cost: "" });
  const cost = parseNairaToKobo(f.cost);
  const create = useMutation({
    mutationFn: () => api.post("/api/v1/admin/tv/products", {
      operator_code: f.operatorCode.trim().toUpperCase(), operator_name: f.operatorName.trim(),
      provider_operator_id: f.operatorId.trim(), provider_service_id: f.serviceId.trim(),
      name: f.name.trim(), cost_kobo: cost,
    }),
    onSuccess: () => { toast("TV package added hidden. Verify the provider IDs and price before listing."); setF({ operatorCode: "", operatorName: "", operatorId: "", serviceId: "", name: "", cost: "" }); void qc.invalidateQueries({ queryKey: ["admin-tv-products"] }); void qc.invalidateQueries({ queryKey: ["costs"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  const set = (k: keyof typeof f) => (v: string) => setF((old) => ({ ...old, [k]: v }));
  return <div className="stack">
    <p className="muted small">TV packages are configured manually. Confirm the provider operator and service/package IDs against your provider account. New packages stay hidden until listed.</p>
    {q.isPending ? <Skeleton h={100} /> : q.isError ? <Banner tone="error">{friendly(q.error)}</Banner> :
      <div className="card flush scroll-x"><table className="table"><thead><tr><th>Operator / package</th><th>Provider IDs</th><th className="r">Cost</th><th className="r">Customer price</th><th>Status</th><th></th></tr></thead>
        <tbody>{q.data.map((p) => <tr key={p.id}><td>{p.operator_name}<div className="muted xs">{p.operator_code} · {p.name}</div></td><td className="xs">Operator: {p.provider_operator_id}<div>Service: {p.provider_service_id}</div></td><td className="r">{p.unit_cost ? `₦${p.unit_cost}` : "—"}</td><td className="r">{p.price_blocked ? <span className="badge bad">blocked</span> : p.unit_price ? `₦${p.unit_price}` : "—"}</td><td>{!p.active ? <span className="badge bad">inactive</span> : p.listed ? <span className="badge">listed</span> : <span className="muted">hidden</span>}</td><td><ListedButton listed={p.listed} busy={toggle.isPending && toggle.variables?.id === p.id} onClick={() => toggle.mutate({ id: p.id, listed: !p.listed })} /></td></tr>)}</tbody></table></div>}
    <details className="card"><summary><strong>Add TV package</strong></summary><div className="stack" style={{ marginTop: 12 }}>
      <div className="row"><div className="grow"><TextField label="Operator code" value={f.operatorCode} onChange={set("operatorCode")} hint="e.g. DSTV" /></div><div className="grow"><TextField label="Operator name" value={f.operatorName} onChange={set("operatorName")} /></div></div>
      <div className="row"><div className="grow"><TextField label="Provider operator ID" value={f.operatorId} onChange={set("operatorId")} /></div><div className="grow"><TextField label="Provider service/package ID" value={f.serviceId} onChange={set("serviceId")} /></div></div>
      <TextField label="Package name" value={f.name} onChange={set("name")} /><MoneyField label="Provider cost" value={f.cost} onChange={set("cost")} />
      <Button loading={create.isPending} disabled={!f.operatorCode.trim() || !f.operatorName.trim() || !f.operatorId.trim() || !f.serviceId.trim() || !f.name.trim() || cost === null || cost <= 0} onClick={() => create.mutate()}>Add hidden package</Button>
    </div></details>
  </div>;
}

export default function Catalogue() {
  const [tab, setTab] = useState<"data" | "electricity" | "exams" | "tv">("data");
  return (
    <div className="stack">
      <div className="tabs" role="tablist">{([["data", "Data plans"], ["electricity", "Electricity"], ["exams", "Exam PINs"], ["tv", "TV packages"]] as const).map(([k, l]) => <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === "data" ? <DataPlans /> : tab === "electricity" ? <Discos /> : tab === "exams" ? <Exams /> : <TVPackages />}
    </div>
  );
}
