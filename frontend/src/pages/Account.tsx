import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { PinPad } from "../components/PinPad";
import { useToast } from "../components/Toast";
import { Banner, Button, KV, LinkButton, PageHead, Skeleton, TextField } from "../components/ui";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { STAFF_ROLES, type SessionRow } from "../lib/types";

export default function Account() {
  const { me, signOut, refreshMe } = useAuth();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [email, setEmail] = useState(me?.email ?? "");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionRow[]>("/api/v1/auth/sessions") });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/auth/sessions/${id}`),
    onSuccess: () => { toast("Device signed out"); void qc.invalidateQueries({ queryKey: ["sessions"] }); },
    onError: (e) => toast(friendly(e), "error"),
  });
  if (!me) return null;
  return (
    <div className="stack">
      <PageHead title="Account" />
      <section className="card stack-sm"><dl style={{ margin: 0 }}><KV k="Name" v={me.full_name} /><KV k="Phone" v={me.phone} />{me.role !== "USER" && <KV k="Role" v={me.role} />}</dl>
        <form className="stack-sm" onSubmit={async (e: FormEvent) => { e.preventDefault(); setEmailBusy(true); setEmailError(null); try { await api.put("/api/v1/users/me/email", { email: email.trim().toLowerCase() }); await refreshMe(); toast("Email address saved"); } catch (err) { setEmailError(friendly(err)); } finally { setEmailBusy(false); } }}>
          <TextField label="Email address (required for wallet funding)" value={email} onChange={setEmail} type="email" autoComplete="email" />
          {emailError && <Banner tone="error">{emailError}</Banner>}
          <Button type="submit" block loading={emailBusy} disabled={!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())}>Save email</Button>
        </form></section>
      <section className="card stack-sm">
        <div className="row between"><div><strong>Rewards & referrals</strong><p className="muted small">Share your invite code or redeem a promo.</p></div><LinkButton to="/rewards" variant="secondary" sm>Open rewards</LinkButton></div>
      </section>
      <section className="card stack-sm">
        <div className="row between"><div><strong>Transaction PIN</strong><p className="muted small">{me.has_pin ? "Required for every payment." : "Not set yet: you need one to pay."}</p></div>
          <LinkButton to="/account/pin" variant="secondary" sm>{me.has_pin ? "Change" : "Set PIN"}</LinkButton></div>
      </section>
      <section className="stack-sm"><h2 className="section-title">Signed-in devices</h2>
        <div className="card flush">{sessions.isPending ? <div style={{ padding: "var(--s4)" }}><Skeleton h={44} /></div> : sessions.isError ? <div style={{ padding: "var(--s4)" }}><Banner tone="error">{friendly(sessions.error)}</Banner></div> :
          <div className="list">{sessions.data.map((s) => (
            <div key={s.id} className="list-row"><span className="grow"><span className="title">{s.device ?? "Unnamed device"}{s.current ? " (this device)" : ""}</span><span className="muted xs" style={{ display: "block" }}>{fmtDateTime(s.created_at)}{s.ip ? ` · ${s.ip}` : ""}</span></span>
              {!s.current && <Button variant="secondary" sm loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>Sign out</Button>}</div>))}</div>}</div></section>
      {STAFF_ROLES.includes(me.role) && <LinkButton to="/admin" variant="secondary" block>Open admin</LinkButton>}
      <Button variant="secondary" block onClick={() => void signOut()}>Log out</Button>
    </div>
  );
}

export function SetPin() {
  const { me, refreshMe } = useAuth();
  const nav = useNavigate();
  const { toast } = useToast();
  const first = (useLocation().state as { first?: boolean } | null)?.first;
  const [old, setOld] = useState(""); const [pin, setPin] = useState(""); const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const changing = !!me?.has_pin;
  const valid = pin.length === 4 && pin === again && (changing ? old.length === 4 : old.length >= 1);

  async function submit(e: FormEvent) {
    e.preventDefault(); if (!valid) return;
    setBusy(true); setError(null);
    try {
      if (changing) await api.post("/api/v1/auth/pin/change", { current_pin: old, new_pin: pin });
      else await api.post("/api/v1/auth/pin/set", { password: old, pin });
      await refreshMe(); toast(changing ? "PIN changed" : "PIN set"); nav("/home", { replace: true });
    } catch (err) { setError(friendly(err)); } finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <PageHead title={changing ? "Change PIN" : "Set your PIN"} sub={first ? "One last step: choose a 4-digit PIN to confirm every payment." : undefined} back={first ? undefined : "/account"} />
      <form className="stack" onSubmit={submit}>
        {changing ? <div className="stack-sm"><span className="section-title">Current PIN</span><PinPad label="Current PIN" value={old} onChange={setOld} /></div>
          : <TextField label="Account password" value={old} onChange={setOld} type="password" autoComplete="current-password" hint="We ask for your password once, to protect your PIN." />}
        <div className="stack-sm"><span className="section-title">New PIN</span><PinPad label="New PIN" value={pin} onChange={setPin} /></div>
        <div className="stack-sm"><span className="section-title">Repeat new PIN</span><PinPad label="Repeat new PIN" value={again} onChange={setAgain} />
          {again.length === 4 && again !== pin && <p className="field-error" role="alert">PINs do not match</p>}</div>
        <p className="hint">Avoid obvious PINs like 1234 or 1111.</p>
        {error && <Banner tone="error">{error}</Banner>}
        <Button type="submit" block loading={busy} disabled={!valid}>{changing ? "Change PIN" : "Save PIN"}</Button>
        {first && <Link to="/home" className="center small">Skip for now</Link>}
      </form>
    </div>
  );
}
