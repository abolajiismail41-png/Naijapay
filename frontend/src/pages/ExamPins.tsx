import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ReviewSheet } from "../components/ReviewSheet";
import { useToast } from "../components/Toast";
import { Banner, Button, Empty, PageHead, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";
import { formatKobo } from "../lib/money";
import type { ExamProduct, ExamQuote, Txn } from "../lib/types";

export default function ExamPins() {
  const { toast } = useToast();
  const products = useQuery({ queryKey: ["exam-products"], queryFn: () => api.get<ExamProduct[]>("/api/v1/education/products") });
  const [id, setId] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [open, setOpen] = useState(false);
  const product = products.data?.find((p) => p.id === id) ?? null;
  const quote = useQuery({
    queryKey: ["exam-quote", id, qty], enabled: !!product, retry: false,
    queryFn: () => api.post<ExamQuote>("/api/v1/education/quote", { product_id: id, quantity: qty }),
  });

  const qd = quote.data;
  return (
    <div className="stack">
      <PageHead title="Exam PINs" sub="Result checker PINs for WAEC and NECO." back="/pay" />
      {products.isPending ? <Skeleton h={120} />
        : products.isError ? <Banner tone="error">{friendly(products.error)}</Banner>
        : products.data.length === 0 ? <div className="card"><Empty title="Not available right now" /></div>
        : <div className="card flush"><div className="list" role="radiogroup" aria-label="Exam products">
            {products.data.map((p) => (
              <button key={p.id} type="button" role="radio" aria-checked={id === p.id} className="radio-row" onClick={() => { setId(p.id); setQty(1); }}>
                <span className="radio-dot" /><span className="grow"><strong>{p.name}</strong></span><strong className="num">{formatKobo(p.unit_price_kobo)}</strong>
              </button>))}
          </div></div>}
      {product && (
        <>
          <div className="row between card"><span>Quantity</span>
            <span className="row">
              <Button variant="secondary" sm aria-label="Fewer" disabled={qty <= 1} onClick={() => setQty(qty - 1)}>−</Button>
              <strong className="num" style={{ minWidth: 24, textAlign: "center" }} aria-live="polite">{qty}</strong>
              <Button variant="secondary" sm aria-label="More" disabled={qty >= product.max_quantity} onClick={() => setQty(qty + 1)}>+</Button>
            </span></div>
          {quote.isError && <Banner tone="error">{friendly(quote.error)}</Banner>}
          {qd && <div className="card"><div className="row between"><span className="muted">You pay</span><strong className="num" style={{ fontSize: "var(--t-lg)" }}>{qd.price}</strong></div></div>}
          <Button block disabled={!qd} onClick={() => setOpen(true)}>Review</Button>
          {qd && (
            <ReviewSheet
              open={open} onClose={() => setOpen(false)} title="Review exam PINs"
              lines={[["Product", product.name], ["Quantity", String(qty)], ["Each", qd.unit_price]]} total={qd.price}
              note="Your PINs appear on the receipt as soon as the payment is confirmed."
              onPriceChanged={(m) => { toast(m); void quote.refetch(); void products.refetch(); }}
              submit={({ pinToken, idempotencyKey }) =>
                api.post<Txn>("/api/v1/education", { product_id: product.id, quantity: qty, confirmed_price_kobo: qd.price_kobo }, { pinToken, idempotencyKey })}
            />
          )}
        </>
      )}
    </div>
  );
}
