import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useState } from "react";
import { Banner, Button, MoneyField, Skeleton, TextField } from "../components/ui";
import { useToast } from "../components/Toast";
import { api, friendly } from "../lib/api";
import { formatKobo, parseNairaToKobo } from "../lib/money";
import { fmtDateTime } from "../lib/format";

interface Campaign { id: string; code: string; name: string; description: string; reward_kobo: number; minimum_qualifying_purchase_kobo: number; max_redemptions: number | null; starts_at: string | null; ends_at: string | null; active: boolean; created_at: string; redemptions: number }

export default function Promotions() {
  const qc = useQueryClient(); const { toast } = useToast();
  const [code, setCode] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState("");
  const [reward, setReward] = useState("100"); const [minimum, setMinimum] = useState("0"); const [cap, setCap] = useState("100");
  const campaigns = useQuery({ queryKey: ["admin-promotions"], queryFn: () => api.get<Campaign[]>("/api/v1/admin/promotions") });
  const create = useMutation({
    mutationFn: (body: unknown) => api.post<Campaign>("/api/v1/admin/promotions", body),
    onSuccess: () => { toast("Promotion campaign created"); setCode(""); setName(""); setDescription(""); void qc.invalidateQueries({ queryKey: ["admin-promotions"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => api.patch(`/api/v1/admin/promotions/${id}`, { active }),
    onSuccess: () => { toast("Campaign updated"); void qc.invalidateQueries({ queryKey: ["admin-promotions"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  const rewardKobo = parseNairaToKobo(reward); const minimumKobo = parseNairaToKobo(minimum);
  const valid = /^[A-Za-z0-9_-]{3,32}$/.test(code.trim()) && name.trim().length >= 2 && rewardKobo !== null && rewardKobo > 0 && minimumKobo !== null && minimumKobo >= 0 && (!cap.trim() || (/^\d+$/.test(cap) && Number(cap) > 0));
  function submit(e: FormEvent) {
    e.preventDefault(); if (!valid) return;
    create.mutate({ code: code.trim().toUpperCase(), name: name.trim(), description: description.trim(), reward_kobo: rewardKobo,
      minimum_qualifying_purchase_kobo: minimumKobo, max_redemptions: cap.trim() ? Number(cap) : null, active: true });
  }
  return <div className="stack">
    <section className="card stack">
      <h2>Create a promo campaign</h2>
      <p className="muted small">Amounts are entered in naira and stored in integer kobo. Campaign rewards are wallet credits funded through the promotions expense account.</p>
      <form className="stack" onSubmit={submit}>
        <TextField label="Promo code" value={code} onChange={(v) => setCode(v.toUpperCase().replace(/[^A-Z0-9_-]/g, ""))} maxLength={32} placeholder="WELCOME100" />
        <TextField label="Campaign name" value={name} onChange={setName} maxLength={100} />
        <TextField label="Description (optional)" value={description} onChange={setDescription} maxLength={300} />
        <MoneyField label="Wallet reward" value={reward} onChange={setReward} hint="Example: 100 means ₦100." />
        <MoneyField label="Minimum successful bill purchase (optional)" value={minimum} onChange={setMinimum} hint="0 means no purchase qualification is required." />
        <TextField label="Maximum redemptions (optional)" value={cap} onChange={setCap} inputMode="numeric" hint="Leave blank for no global cap. Use a conservative cap for public campaigns." />
        {create.isError && <Banner tone="error">{friendly(create.error)}</Banner>}
        <Button type="submit" block loading={create.isPending} disabled={!valid}>Create campaign</Button>
      </form>
    </section>
    <section className="stack-sm"><h2 className="section-title">Campaigns</h2>
      {campaigns.isError && <Banner tone="error">{friendly(campaigns.error)}</Banner>}
      {campaigns.isPending ? <Skeleton h={90} /> : campaigns.data?.length ? <div className="card flush scroll-x"><table className="table"><thead><tr><th>Campaign</th><th>Reward</th><th>Redemptions</th><th>Status</th><th>Action</th></tr></thead><tbody>
        {campaigns.data.map((c) => <tr key={c.id}><td><strong>{c.code}</strong><span className="muted small" style={{ display: "block" }}>{c.name}</span><span className="muted xs">Created {fmtDateTime(c.created_at)}</span></td><td>{formatKobo(c.reward_kobo)}<span className="muted xs" style={{ display: "block" }}>Min spend {formatKobo(c.minimum_qualifying_purchase_kobo)}</span></td><td>{c.redemptions}{c.max_redemptions ? ` / ${c.max_redemptions}` : " / ∞"}</td><td><span className={c.active ? "badge ok" : "badge neutral"}>{c.active ? "Active" : "Paused"}</span></td><td><Button variant="secondary" sm loading={toggle.isPending && toggle.variables?.id === c.id} onClick={() => toggle.mutate({ id: c.id, active: !c.active })}>{c.active ? "Pause" : "Activate"}</Button></td></tr>)}
      </tbody></table></div> : <div className="card"><p className="muted small">No campaigns created yet.</p></div>}
    </section>
  </div>;
}
