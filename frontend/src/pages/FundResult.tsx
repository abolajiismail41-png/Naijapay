import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Banner, LinkButton, PageHead, Spinner, StatusBadge } from "../components/ui";
import { api, friendly } from "../lib/api";
import { formatKobo } from "../lib/money";
import { store } from "../lib/storage";
import type { Funding } from "../lib/types";
import { PENDING_FUNDING } from "./Fund";

const OPEN = ["INITIATED", "PENDING"];

/** The only thing that counts is the status the server reports after verifying with the processor. */
export default function FundResult() {
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const raw = sp.get("reference") ?? sp.get("trxref") ?? store.get(PENDING_FUNDING) ?? "";
  const reference = raw.replace(/-\d+$/, "").replace(/^fnd-/, "fnd_"); // Normalize provider-safe reference back to our internal fnd_ reference
  const [slow, setSlow] = useState(false);
  const q = useQuery({
    queryKey: ["funding", reference], enabled: /^fnd_[0-9a-f]{32}$/.test(reference),
    queryFn: () => api.get<Funding>(`/api/v1/wallet/funding/${reference}`),
    refetchInterval: (query) => (query.state.data && !OPEN.includes(query.state.data.status) ? false : 2500),
  });
  const status = q.data?.status;
  useEffect(() => { if (status === "SUCCESSFUL") { void qc.invalidateQueries({ queryKey: ["wallet"] }); store.remove(PENDING_FUNDING); } }, [status, qc]);
  useEffect(() => { const t = setTimeout(() => setSlow(true), 60_000); return () => clearTimeout(t); }, []);

  if (!reference) return <div className="stack"><PageHead title="Payment" /><Banner tone="warn">We could not find this payment. <a href="/activity">Check your activity</a>.</Banner></div>;
  return (
    <div className="stack">
      <PageHead title="Payment status" />
      {q.isError ? <Banner tone="error">{friendly(q.error)}</Banner> : !q.data ? <div className="card center"><Spinner /><p className="muted" style={{ marginTop: 8 }}>Checking your payment…</p></div> : (
        <div className="card stack">
          <div className="row between"><strong>{formatKobo(q.data.amount_kobo)} top-up</strong><StatusBadge status={q.data.status} /></div>
          <p>{q.data.message}</p>
          {OPEN.includes(q.data.status) && slow && <Banner tone="info">Still confirming. If you have paid, your wallet will be credited automatically once the payment is confirmed: you do not need to pay again.</Banner>}
          {q.data.status === "MISMATCH" && <Banner tone="warn">Our team is reviewing this payment. Your money is safe.</Banner>}
          <p className="muted xs">Reference <span className="mono">{q.data.reference}</span></p>
        </div>
      )}
      <LinkButton to="/home" variant={status === "SUCCESSFUL" ? "primary" : "secondary"} block>Back to home</LinkButton>
    </div>
  );
}
