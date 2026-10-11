import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
import { Banner, Button, Empty, KV, PageHead, Skeleton, TextField } from "../components/ui";
import { api, friendly } from "../lib/api";
import { formatKobo } from "../lib/money";
import type { Txn, TVOperator, TVPlan, TVQuote, TVValidation } from "../lib/types";

export default function TV() {
  const { toast } = useToast();
  const operators = useQuery({ queryKey: ["tv-operators"], queryFn: () => api.get<TVOperator[]>("/api/v1/tv/operators") });
  const [operatorCode, setOperatorCode] = useState("");
  const [smartcard, setSmartcard] = useState("");
  const [validation, setValidation] = useState<TVValidation | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [productId, setProductId] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const operator = operators.data?.find((o) => o.code === operatorCode) ?? null;
  useEffect(() => {
    if (operators.data?.length && !operatorCode) setOperatorCode(operators.data[0]!.code);
  }, [operators.data, operatorCode]);
  useEffect(() => { setValidation(null); setValidationError(null); setProductId(null); }, [operatorCode, smartcard]);

  const plans = useQuery({ queryKey: ["tv-plans", operatorCode], enabled: !!validation && !!operatorCode,
    queryFn: () => api.get<TVPlan[]>("/api/v1/tv/plans", { operator_code: operatorCode }) });
  const product = plans.data?.find((p) => p.id === productId) ?? null;
  const quote = useQuery({ queryKey: ["tv-quote", validation?.validation_id, productId], enabled: !!validation && !!product,
    retry: false, queryFn: () => api.post<TVQuote>("/api/v1/tv/quote", { validation_id: validation!.validation_id, product_id: product!.id }) });

  async function verify() {
    setChecking(true); setValidationError(null);
    try { setValidation(await api.post<TVValidation>("/api/v1/tv/validate", { operator_code: operatorCode, smartcard_number: smartcard.replace(/\s/g, "") })); }
    catch (e) { setValidationError(friendly(e)); }
    finally { setChecking(false); }
  }

  return <div className="stack">
    <PageHead title="TV subscriptions" sub="Verify the decoder before renewing its package." back="/pay" />
    {operators.isPending ? <Skeleton h={120} /> : operators.isError ? <Banner tone="error">{friendly(operators.error)}</Banner>
      : operators.data.length === 0 ? <div className="card"><Empty title="TV subscriptions are unavailable" /></div> : <>
        <div className="field"><label htmlFor="tv-operator">TV provider</label>
          <select id="tv-operator" className="input" value={operatorCode} onChange={(e) => setOperatorCode(e.target.value)}>
            {operators.data.map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
          </select>
        </div>
        <TextField label="Smartcard / IUC number" value={smartcard} onChange={(v) => setSmartcard(v.replace(/[^\d\s]/g, ""))} inputMode="numeric" error={validationError} />
        {!validation && <Button block loading={checking} disabled={!operator || smartcard.replace(/\s/g, "").length < 8} onClick={() => void verify()}>Verify smartcard</Button>}
        {validation && <>
          <section className="card"><dl style={{ margin: 0 }}>
            <KV k="Customer name" v={validation.customer_name} />
            <KV k="Smartcard" v={validation.smartcard_number} />
            {validation.current_bouquet && <KV k="Current package" v={validation.current_bouquet} />}
          </dl><p className="hint">Confirm the name and smartcard number before continuing.</p></section>
          {plans.isPending ? <Skeleton h={100} /> : plans.isError ? <Banner tone="error">{friendly(plans.error)}</Banner>
            : plans.data.length === 0 ? <div className="card"><Empty title="No packages available for this provider" /></div>
            : <div className="card flush"><div className="list" role="radiogroup" aria-label="TV packages">
                {plans.data.map((p) => <button key={p.id} type="button" role="radio" aria-checked={productId === p.id} className="radio-row" onClick={() => setProductId(p.id)}>
                  <span className="radio-dot" /><span className="grow"><strong>{p.name}</strong></span><strong className="num">{formatKobo(p.price_kobo)}</strong>
                </button>)}
              </div></div>}
          {quote.isError && <Banner tone="error">{friendly(quote.error)}</Banner>}
          {quote.data && <div className="card"><div className="row between"><span className="muted">You pay</span><strong className="num" style={{ fontSize: "var(--t-lg)" }}>{quote.data.price}</strong></div></div>}
          <Button block disabled={!quote.data} onClick={() => setReviewOpen(true)}>Review subscription</Button>
          <Button block variant="ghost" onClick={() => setValidation(null)}>Change smartcard</Button>
          {quote.data && product && <ReviewSheet open={reviewOpen} onClose={() => setReviewOpen(false)} title="Review TV subscription"
            lines={[["Provider", quote.data.operator], ["Package", quote.data.product], ["Customer", quote.data.customer_name], ["Smartcard", quote.data.smartcard_number]]}
            total={quote.data.price} note="Your wallet is charged once. If the provider result is uncertain, the transaction stays pending while we verify it."
            onPriceChanged={(m) => { toast(m); void quote.refetch(); void plans.refetch(); }}
            submit={({ pinToken, idempotencyKey }) => api.post<Txn>("/api/v1/tv", {
              validation_id: validation.validation_id, product_id: product.id, confirmed_price_kobo: quote.data!.price_kobo,
            }, { pinToken, idempotencyKey })} />}
        </>}
      </>}
  </div>;
}
