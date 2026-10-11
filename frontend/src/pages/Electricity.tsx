import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Segmented } from "../components/forms";
import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
import { Banner, Button, KV, MoneyField, PageHead, Skeleton, TextField } from "../components/ui";
import { api, ApiError, friendly } from "../lib/api";
import { useDebounced } from "../lib/hooks";
import { formatKobo, parseNairaToKobo } from "../lib/money";
import type { Disco, ElectricityQuote, MeterValidation, Txn } from "../lib/types";

const QUICK = ["1000", "2000", "5000", "10000"];

export default function Electricity() {
  const { toast } = useToast();
  const discos = useQuery({ queryKey: ["discos"], queryFn: () => api.get<Disco[]>("/api/v1/electricity/discos"), retry: false });
  const [discoId, setDiscoId] = useState("");
  const [type, setType] = useState<"PREPAID" | "POSTPAID">("PREPAID");
  const [meter, setMeter] = useState("");
  const [meterErr, setMeterErr] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [v, setV] = useState<MeterValidation | null>(null);
  const [amount, setAmount] = useState("");
  const [open, setOpen] = useState(false);

  const disco = discos.data?.find((d) => d.id === discoId) ?? null;
  useEffect(() => { if (discos.data?.length && !discoId) setDiscoId(discos.data[0]!.id); }, [discos.data, discoId]);
  useEffect(() => { if (disco && !disco.meter_types.includes(type)) setType(disco.meter_types[0] ?? "PREPAID"); }, [disco, type]);
  useEffect(() => { setV(null); setMeterErr(null); }, [discoId, type, meter]); // any change means the meter must be verified again

  const kobo = parseNairaToKobo(useDebounced(amount));
  const whole = v !== null && kobo !== null && kobo > 0 && kobo % 100 === 0;
  const quote = useQuery({
    queryKey: ["elec-quote", v?.validation_id, kobo], enabled: whole, retry: false,
    queryFn: () => api.post<ElectricityQuote>("/api/v1/electricity/quote", { validation_id: v!.validation_id, amount_kobo: kobo }),
  });
  const q = whole ? quote.data : undefined;

  async function verify() {
    setChecking(true); setMeterErr(null);
    try { setV(await api.post<MeterValidation>("/api/v1/electricity/validate", { disco_id: discoId, meter_type: type, meter_number: meter.replace(/\s/g, "") })); }
    catch (e) { setMeterErr(friendly(e)); } finally { setChecking(false); }
  }

  if (discos.isPending) return <div className="stack"><PageHead title="Electricity" back="/pay" /><Skeleton h={48} /><Skeleton h={48} /></div>;
  if (discos.isError) return <div className="stack"><PageHead title="Electricity" back="/pay" /><Banner tone={discos.error instanceof ApiError && discos.error.status === 503 ? "warn" : "error"}>{friendly(discos.error)}</Banner></div>;
  if (discos.data.length === 0) return <div className="stack"><PageHead title="Electricity" back="/pay" /><Banner tone="warn">No electricity providers are available right now.</Banner></div>;

  return (
    <div className="stack">
      <PageHead title="Electricity" back="/pay" />
      <div className="field"><label htmlFor="disco">Distribution company</label>
        <select id="disco" className="input" value={discoId} onChange={(e) => setDiscoId(e.target.value)}>{discos.data.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
      {disco && disco.meter_types.length > 1 && <Segmented label="Meter type" value={type} onChange={(k) => setType(k as "PREPAID" | "POSTPAID")} options={disco.meter_types.map((t) => ({ key: t, text: t === "PREPAID" ? "Prepaid" : "Postpaid" }))} />}
      <TextField label="Meter number" value={meter} onChange={(x) => setMeter(x.replace(/[^\d\s]/g, ""))} inputMode="numeric" error={meterErr} />
      {!v && <Button block loading={checking} disabled={meter.replace(/\s/g, "").length < 6 || !discoId} onClick={verify}>Verify meter</Button>}
      {v && (
        <>
          <div className="card"><dl style={{ margin: 0 }}><KV k="Name on meter" v={v.customer_name} />{v.address && <KV k="Address" v={v.address} />}<KV k="Meter" v={v.meter_number} /></dl>
            <p className="hint" style={{ marginTop: 8 }}>Check that this is the right meter before you pay.</p></div>
          <MoneyField label="Amount" value={amount} onChange={setAmount} hint={`Minimum ${formatKobo(v.min_kobo)}`} error={quote.isError && whole ? friendly(quote.error) : null} />
          <div className="chips">{QUICK.map((a) => <button key={a} type="button" className="chip" onClick={() => setAmount(a)}>₦{Number(a).toLocaleString("en-NG")}</button>)}</div>
          {q && <div className="card" aria-live="polite"><dl style={{ margin: 0 }}><KV k="Token value" v={q.amount} /><KV k="Service fee" v={q.service_fee} /><KV k="You pay" v={<strong>{q.price}</strong>} /></dl></div>}
          <Button block disabled={!q} onClick={() => setOpen(true)}>Review</Button>
          {q && (
            <ReviewSheet
              open={open} onClose={() => setOpen(false)} title="Review electricity payment"
              lines={[["Company", v.disco], ["Meter", `${v.meter_number} · ${type === "PREPAID" ? "Prepaid" : "Postpaid"}`], ["Name", v.customer_name], ["Token value", q.amount], ["Service fee", q.service_fee]]}
              total={q.price} note={type === "PREPAID" ? "Your token will appear on the receipt once the payment is confirmed." : undefined}
              onPriceChanged={(m) => { toast(m); void quote.refetch(); }}
              submit={async ({ pinToken, idempotencyKey }) => {
                try { return await api.post<Txn>("/api/v1/electricity", { validation_id: v.validation_id, amount_kobo: kobo, confirmed_price_kobo: q.price_kobo }, { pinToken, idempotencyKey }); }
                catch (e) { if (e instanceof ApiError && e.code === "meter_validation_expired") setV(null); throw e; }
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
