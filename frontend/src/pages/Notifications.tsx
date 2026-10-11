import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BellIcon, CheckIcon } from "../components/icons";
import { Banner, Button, Empty, PageHead, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";

interface NotificationItem {
  id: string; category: string; title: string; body: string; resource_type: string | null;
  resource_reference: string | null; payload: Record<string, unknown>; read_at: string | null; created_at: string;
}
interface NotificationPage { items: NotificationItem[]; next_cursor: string | null; unread_count: number }
interface Preferences { in_app_enabled: boolean; email_enabled: boolean; sms_enabled: boolean; push_enabled: boolean; email_address: string | null }

export default function Notifications() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [emailOn, setEmailOn] = useState(false);
  const [smsOn, setSmsOn] = useState(false);
  const list = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<NotificationPage>("/api/v1/notifications", { limit: 50 }) });
  const prefs = useQuery({ queryKey: ["notification-preferences"], queryFn: () => api.get<Preferences>("/api/v1/notifications/preferences") });
  const markAll = useMutation({ mutationFn: () => api.post("/api/v1/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const markOne = useMutation({ mutationFn: (id: string) => api.post("/api/v1/notifications/read", { ids: [id] }), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const savePrefs = useMutation({
    mutationFn: () => api.patch<Preferences>("/api/v1/notifications/preferences", {
      email_enabled: emailOn, sms_enabled: smsOn, email_address: email.trim() || null,
    }),
    onSuccess: (data) => { qc.setQueryData(["notification-preferences"], data); },
  });
  const items = list.data?.items ?? [];
  const preference = prefs.data;
  useEffect(() => {
    if (!preference) return;
    setEmail(preference.email_address ?? "");
    setEmailOn(preference.email_enabled);
    setSmsOn(preference.sms_enabled);
  }, [preference]);

  return <div className="stack">
    <PageHead title="Notifications" sub="Important updates about your wallet and purchases." />
    {list.isError && <Banner tone="error">{friendly(list.error)}</Banner>}
    {markAll.isError && <Banner tone="error">{friendly(markAll.error)}</Banner>}
    {savePrefs.isError && <Banner tone="error">{friendly(savePrefs.error)}</Banner>}
    <section className="card stack-sm">
      <div className="row between center"><div><h2>Inbox</h2><p className="muted small">{list.data?.unread_count ?? 0} unread</p></div>
        <Button variant="secondary" sm disabled={!list.data?.unread_count || markAll.isPending} loading={markAll.isPending} onClick={() => markAll.mutate()}>Mark all read</Button></div>
      {list.isPending ? <div className="stack"><Skeleton h={70} /><Skeleton h={70} /><Skeleton h={70} /></div>
        : items.length === 0 ? <Empty title="You're all caught up"><span>We'll show important wallet and transaction updates here.</span></Empty>
        : <div className="list">{items.map((n) => <article key={n.id} className="list-row" style={{ alignItems: "flex-start", background: n.read_at ? undefined : "var(--accent-soft)" }}>
          <span className="icon" aria-hidden="true"><BellIcon width={18} height={18} /></span>
          <div className="grow" style={{ minWidth: 0 }}><div className="row between center" style={{ gap: 8 }}><strong className="title">{n.title}</strong>{!n.read_at && <span className="badge ok">New</span>}</div>
            <p className="small" style={{ marginTop: 4 }}>{n.body}</p>
            <span className="muted xs" style={{ display: "block", marginTop: 6 }}>{fmtDateTime(n.created_at)}{n.resource_reference ? ` · Ref ${n.resource_reference}` : ""}</span>
          </div>
          {!n.read_at && <Button variant="ghost" sm aria-label={`Mark ${n.title} as read`} onClick={() => markOne.mutate(n.id)}><CheckIcon width={16} height={16} /></Button>}
        </article>)}</div>}
    </section>

    <section className="card stack-sm">
      <div><h2>Delivery preferences</h2><p className="muted small">In-app alerts remain available. External messages are sent only when a provider is configured.</p></div>
      {prefs.isError && <Banner tone="error">{friendly(prefs.error)}</Banner>}
      <label className="check-row"><input type="checkbox" checked={emailOn} onChange={(e) => setEmailOn(e.target.checked)} /> <span><strong>Email updates</strong><small>Receive account and transaction alerts by email.</small></span></label>
      {emailOn && <label className="field"><span>Email address</span><input className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" /></label>}
      <label className="check-row"><input type="checkbox" checked={smsOn} onChange={(e) => setSmsOn(e.target.checked)} /> <span><strong>SMS updates</strong><small>Send concise transaction alerts to your verified phone number.</small></span></label>
      <div className="banner info">Push notifications are not enabled yet. They will become available after device registration and push-provider setup.</div>
      <Button block loading={savePrefs.isPending} onClick={() => savePrefs.mutate()} disabled={emailOn && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())}>Save preferences</Button>
      {savePrefs.isSuccess && <p className="small" role="status">Preferences saved.</p>}
    </section>
  </div>;
}
