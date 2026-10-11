import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CopyButton, Banner, Button, Empty, PageHead, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";
import { formatKobo } from "../lib/money";
import { fmtDateTime } from "../lib/format";

interface Reward { id: string; referred_user_id: string; transaction_id: string; amount_kobo: number; created_at: string }
interface ReferralSummary { code: string; share_text: string; total_invites: number; pending_invites: number; rewarded_invites: number; total_rewards_kobo: number; reward_enabled: boolean; reward_amount_kobo: number; minimum_qualifying_purchase_kobo: number; rewards: Reward[] }
interface PromoResult { code: string; reward_kobo: number; journal_reference: string; redeemed_at: string }

export default function Rewards() {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const summary = useQuery({ queryKey: ["referrals"], queryFn: () => api.get<ReferralSummary>("/api/v1/referrals/me") });
  const redeem = useMutation({
    mutationFn: () => api.post<PromoResult>("/api/v1/promotions/redeem", { code: code.trim().toUpperCase() }),
    onSuccess: () => { setCode(""); void qc.invalidateQueries({ queryKey: ["wallet"] }); void qc.invalidateQueries({ queryKey: ["referrals"] }); },
  });
  return <div className="stack">
    <PageHead title="Rewards & referrals" sub="Invite friends and redeem promotional wallet rewards." />
    {summary.isError && <Banner tone="error">{friendly(summary.error)}</Banner>}
    <section className="card stack-sm">
      <h2>Your referral code</h2>
      {summary.isPending ? <Skeleton h={44} /> : summary.data && <>
        <div className="row between center"><strong className="mono" style={{ fontSize: "1.35rem", letterSpacing: ".08em" }}>{summary.data.code}</strong><CopyButton text={summary.data.code} label="Copy code" /></div>
        <p className="muted small">Share your code with friends. Rewards are paid only after a referred customer completes their first qualifying successful bill payment.</p>
        {!summary.data.reward_enabled ? <Banner tone="warn">Referral payouts are currently disabled. Existing referrals will not be paid unless the programme is enabled before a qualifying purchase.</Banner> : <Banner tone="info">Current reward: {formatKobo(summary.data.reward_amount_kobo)} after an eligible bill payment of at least {formatKobo(summary.data.minimum_qualifying_purchase_kobo)}.</Banner>}
        <CopyButton text={summary.data.share_text} label="Copy invite message" />
        <div className="grid-3" style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: "var(--s2)" }}>
          <div className="card"><strong>{summary.data.total_invites}</strong><p className="muted xs">Invites</p></div>
          <div className="card"><strong>{summary.data.pending_invites}</strong><p className="muted xs">Pending</p></div>
          <div className="card"><strong>{summary.data.rewarded_invites}</strong><p className="muted xs">Rewarded</p></div>
        </div>
        <div><p className="muted small">Total referral rewards</p><h2>{formatKobo(summary.data.total_rewards_kobo)}</h2></div>
      </>}
    </section>
    <section className="card stack-sm">
      <h2>Redeem a promo code</h2>
      <p className="muted small">Enter a valid active campaign code. Rewards are credited to your wallet once, subject to campaign rules.</p>
      <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); if (code.trim()) redeem.mutate(); }}>
        <label className="field"><span>Promo code</span><input className="input" value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ""))} maxLength={32} autoCapitalize="characters" placeholder="WELCOME" /></label>
        {redeem.isError && <Banner tone="error">{friendly(redeem.error)}</Banner>}
        {redeem.isSuccess && <Banner tone="info">{redeem.data.code} redeemed. {formatKobo(redeem.data.reward_kobo)} has been credited to your wallet.</Banner>}
        <Button type="submit" block loading={redeem.isPending} disabled={code.trim().length < 3}>Redeem code</Button>
      </form>
    </section>
    <section className="card stack-sm">
      <h2>Referral reward history</h2>
      {summary.isPending ? <Skeleton h={70} /> : !summary.data?.rewards.length ? <Empty title="No referral rewards yet">Your reward history will appear here after an eligible referral qualifies.</Empty> : <div className="list">{summary.data.rewards.map((r) => <div className="list-row" key={r.id}><span className="grow"><strong>Referral reward</strong><span className="muted xs" style={{ display: "block" }}>{fmtDateTime(r.created_at)}</span></span><strong>{formatKobo(r.amount_kobo)}</strong></div>)}</div>}
    </section>
  </div>;
}
