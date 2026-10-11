import { MoneyField, TextField } from "../components/ui";
import { parseNairaToKobo, parseScaled } from "../lib/money";

export const METHODS = ["PERCENT_MARKUP", "FIXED_MARKUP", "CUSTOM_PRICE", "FACE_VALUE"] as const;
export interface PState { method: (typeof METHODS)[number]; markupPct: string; markupNaira: string; customNaira: string; feeNaira: string; discNaira: string; discPct: string; roundNaira: string; capAtFace: boolean }
export const emptyP = (): PState => ({ method: "PERCENT_MARKUP", markupPct: "2", markupNaira: "", customNaira: "", feeNaira: "", discNaira: "", discPct: "", roundNaira: "", capAtFace: false });

/** Builds the API body with exact integer maths (percent -> basis points, naira -> kobo). */
export function buildPricing(s: PState): { body: Record<string, unknown> } | { error: string } {
  const kobo = (v: string, what: string) => { if (!v.trim()) return 0; const k = parseNairaToKobo(v); if (k === null) throw new Error(`${what} is not a valid amount`); return k; };
  const bps = (v: string, what: string) => { if (!v.trim()) return 0; const k = parseScaled(v, 2); if (k === null) throw new Error(`${what} is not a valid percentage`); return k; };
  try {
    const body: Record<string, unknown> = { method: s.method, fee_kobo: kobo(s.feeNaira, "Fee"), discount_kobo: kobo(s.discNaira, "Discount"), discount_bps: bps(s.discPct, "Discount %"), rounding_kobo: s.roundNaira.trim() ? Math.max(1, kobo(s.roundNaira, "Rounding")) : 1, cap_at_face: s.capAtFace };
    if (s.method === "PERCENT_MARKUP") body.markup_bps = bps(s.markupPct, "Markup %");
    if (s.method === "FIXED_MARKUP") body.markup_kobo = kobo(s.markupNaira, "Markup");
    if (s.method === "CUSTOM_PRICE") { const c = kobo(s.customNaira, "Price"); if (c <= 0) throw new Error("Enter the customer price"); body.custom_price_kobo = c; }
    return { body };
  } catch (e) { return { error: (e as Error).message }; }
}

export function PricingFields({ s, set }: { s: PState; set: (p: PState) => void }) {
  const up = (patch: Partial<PState>) => set({ ...s, ...patch });
  return (
    <div className="stack">
      <div className="field"><label htmlFor="pm">Pricing method</label>
        <select id="pm" className="input" value={s.method} onChange={(e) => up({ method: e.target.value as PState["method"] })}>{METHODS.map((m) => <option key={m} value={m}>{m.replace("_", " ").toLowerCase()}</option>)}</select></div>
      {s.method === "PERCENT_MARKUP" && <TextField label="Markup % of provider cost" value={s.markupPct} onChange={(v) => up({ markupPct: v })} inputMode="decimal" />}
      {s.method === "FIXED_MARKUP" && <MoneyField label="Fixed markup (per unit)" value={s.markupNaira} onChange={(v) => up({ markupNaira: v })} />}
      {s.method === "CUSTOM_PRICE" && <MoneyField label="Customer price (per unit)" value={s.customNaira} onChange={(v) => up({ customNaira: v })} />}
      {s.method === "FACE_VALUE" && <p className="hint">Customer pays the face value plus the fee; your margin is the provider discount.</p>}
      <MoneyField label="Service fee (optional)" value={s.feeNaira} onChange={(v) => up({ feeNaira: v })} />
      <div className="row"><div className="grow"><MoneyField label="Discount ₦" value={s.discNaira} onChange={(v) => up({ discNaira: v })} /></div><div className="grow"><TextField label="Discount %" value={s.discPct} onChange={(v) => up({ discPct: v })} inputMode="decimal" /></div></div>
      <MoneyField label="Round price up to nearest (optional)" value={s.roundNaira} onChange={(v) => up({ roundNaira: v })} hint="Leave blank for no rounding; 1 = whole naira" />
      <label className="row"><input type="checkbox" checked={s.capAtFace} onChange={(e) => up({ capAtFace: e.target.checked })} /> Never sell above face value (airtime)</label>
    </div>
  );
}
