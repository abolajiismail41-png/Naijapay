import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Banner, Button, KV, MoneyField, PageHead } from "../components/ui";
import { Chips } from "../components/forms";
import { DEV_TOOLS } from "../config";
import { api, friendly } from "../lib/api";
import { newKey } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { parseNairaToKobo } from "../lib/money";
import { store } from "../lib/storage";
import type { Funding, FundingQuote } from "../lib/types";
import { WalletCard } from "./Home";

export const PENDING_FUNDING = "np.pendingFunding";
const QUICK = ["1000", "2000", "5000", "10000", "20000"];

export default function Fund() {
  const nav = useNavigate();
  const [amount, setAmount] = useState("");
  const typed = parseNairaToKobo(amount);
  const kobo = parseNairaToKobo(useDebounced(amount));
  const key = useRef(newKey());
  useEffect(() => { key.current = newKey(); }, [kobo]); // a new amount is a new payment
  const quote = useQuery({
    queryKey: ["fund-quote", kobo], enabled: kobo !== null && kobo > 0, retry: false,
    queryFn: () => api.get<FundingQuote>("/api/v1/wallet/funding/quote", { amount_kobo: kobo }),
  });
  const q = quote.data && typed === quote.data.amount_kobo ? quote.data : undefined;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sandbox, setSandbox] = useState<Funding | null>(null);

  async function start() {
    if (!q) return;
    setBusy(true); setError(null);
    try {
      const p = await api.post<Funding>("/api/v1/wallet/funding", { amount_kobo: q.amount_kobo }, { idempotencyKey: key.current });
      store.set(PENDING_FUNDING, p.reference);
      if (!p.authorization_url) { nav(`/fund/result?reference=${p.reference}`); return; }
      if (new URL(p.authorization_url).hostname === "sandbox.pay.local") { setSandbox(p); return; }
      window.location.assign(p.authorization_url);
    } catch (e) { setError(friendly(e)); } finally { setBusy(false); }
  }

  async function simulate() {
    if (!sandbox) return;
    setBusy(true);
    try { await api.post("/api/v1/dev/sandbox/complete-funding", { reference: sandbox.reference }); nav(`/fund/result?reference=${sandbox.reference}`); }
    catch (e) { setError(friendly(e)); } finally { setBusy(false); }
  }

  return (
    <div className="stack">
      <PageHead title="Add money" back="/home" />
      <WalletCard />
      <MoneyField label="How much do you want to add?" value={amount} onChange={setAmount} error={quote.isError ? friendly(quote.error) : typed === null && amount ? "Enter a valid amount" : null} />
      <Chips label="Quick amounts" value={amount} onChange={setAmount} options={QUICK.map((v) => ({ key: v, text: `₦${Number(v).toLocaleString("en-NG")}` }))} />
      {q && (
        <div className="card" aria-live="polite"><dl style={{ margin: 0 }}>
          <KV k="Added to your wallet" v={q.amount} /><KV k="Payment fee" v={q.fee} /><KV k="You pay" v={<strong>{q.total}</strong>} />
        </dl></div>
      )}
      {error && <Banner tone="error">{error}</Banner>}
      {sandbox ? (
        <Banner tone="warn"><div className="stack-sm"><span>Sandbox checkout (local only): no real money moves.</span>
          {DEV_TOOLS ? <Button sm loading={busy} onClick={simulate}>Simulate successful payment</Button> : <span>Dev tools are disabled.</span>}</div></Banner>
      ) : (
        <Button block loading={busy} disabled={!q} onClick={start}>{q ? `Pay ${q.total}` : "Continue"}</Button>
      )}
      <p className="hint">You will be taken to Paystack to pay securely. Your wallet is credited only after Paystack confirms the payment.</p>
    </div>
  );
}
