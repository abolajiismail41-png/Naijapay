import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Chips, PhoneField, usePhone } from "../components/forms";
import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
import { Banner, Button, MoneyField, PageHead } from "../components/ui";
import { api, friendly } from "../lib/api";
import { useDebounced } from "../lib/hooks";
import { formatKobo, parseNairaToKobo } from "../lib/money";
import { label } from "../lib/txn";
import type { Network, PriceQuote, Txn } from "../lib/types";

const NETWORKS: Network[] = ["MTN", "AIRTEL", "GLO", "9MOBILE"];
const QUICK = ["100", "200", "500", "1000", "2000"];

export default function Airtime() {
  const { toast } = useToast();
  const [network, setNetwork] = useState<Network>("MTN");
  const phone = usePhone();
  const [amount, setAmount] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(amount);
  const kobo = parseNairaToKobo(debounced);
  const whole = kobo !== null && kobo > 0 && kobo % 100 === 0;
  const quote = useQuery({
    queryKey: ["airtime-quote", network, kobo], enabled: whole, retry: false,
    queryFn: () => api.post<PriceQuote>("/api/v1/airtime/quote", { network, amount_kobo: kobo }),
  });
  const q = whole ? quote.data : undefined;
  const typed = parseNairaToKobo(amount);
  const amountError = amount && (typed === null || typed % 100 !== 0 || typed === 0) ? "Enter a whole-naira amount" : null;

  return (
    <div className="stack">
      <PageHead title="Airtime" back="/pay" />
      <div className="stack-sm"><span className="section-title">Network</span>
        <Chips label="Network" value={network} onChange={(k) => setNetwork(k as Network)} options={NETWORKS.map((n) => ({ key: n, text: label(n) }))} /></div>
      <PhoneField raw={phone.raw} onChange={phone.setRaw} error={phone.error} />
      <MoneyField label="Amount" value={amount} onChange={setAmount} error={amountError} />
      <Chips label="Quick amounts" value={amount} onChange={setAmount} options={QUICK.map((v) => ({ key: v, text: `₦${Number(v).toLocaleString("en-NG")}` }))} />
      {whole && quote.isError && <Banner tone="error">{friendly(quote.error)}</Banner>}
      {q && (
        <div className="card" aria-live="polite">
          <div className="row between"><span className="muted">You pay</span><strong className="num" style={{ fontSize: "var(--t-lg)" }}>{q.price}</strong></div>
          {q.price_kobo < kobo! && <p className="small" style={{ color: "var(--accent-strong)", marginTop: 4 }}>You save {formatKobo(kobo! - q.price_kobo)} on this top-up</p>}
        </div>
      )}
      <Button block disabled={!phone.valid || !q} onClick={() => setOpen(true)}>Review</Button>
      {q && phone.e164 && (
        <ReviewSheet
          open={open} onClose={() => setOpen(false)} title="Review airtime"
          lines={[["Network", label(network)], ["Number", phone.raw], ["Airtime value", formatKobo(kobo!)]]} total={formatKobo(q.price_kobo)}
          onPriceChanged={(m) => { toast(m); void quote.refetch(); }}
          submit={({ pinToken, idempotencyKey, confirmNetwork }) =>
            api.post<Txn>("/api/v1/airtime", { network, phone: phone.e164, amount_kobo: kobo, confirmed_price_kobo: q.price_kobo, confirm_network: confirmNetwork }, { pinToken, idempotencyKey })}
        />
      )}
    </div>
  );
}
