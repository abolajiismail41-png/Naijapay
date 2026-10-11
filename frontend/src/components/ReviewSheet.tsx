import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api, ApiError, friendly } from "../lib/api";
import { newKey } from "../lib/format";
import type { Txn } from "../lib/types";
import { PinPad } from "./PinPad";
import { Sheet } from "./Sheet";
import { Banner, Button, KV } from "./ui";

export interface SubmitCtx { pinToken: string; idempotencyKey: string; confirmNetwork: boolean }

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  lines: Array<[string, string]>;
  total: string;
  note?: string;
  submit: (ctx: SubmitCtx) => Promise<Txn>;
  onPriceChanged?: (message: string) => void;
}

/**
 * Review -> PIN -> submit. Money safety rules live here:
 * - one idempotency key per attempt, kept across network failures so a retry can never charge twice;
 * - the PIN is exchanged for a short-lived single-use token, never sent with the purchase itself;
 * - nothing is shown as successful here: we hand over to the transaction page, which shows the server's status.
 */
export function ReviewSheet({ open, onClose, title, lines, total, note, submit, onPriceChanged }: Props) {
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [stage, setStage] = useState<"review" | "pin">("review");
  const [pin, setPin] = useState("");
  const [pinKey, setPinKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needFunds, setNeedFunds] = useState(false);
  const [mismatch, setMismatch] = useState<string | null>(null);
  const key = useRef(newKey());
  const token = useRef<{ value: string; at: number } | null>(null);
  const confirmNetwork = useRef(false);

  useEffect(() => {
    if (open) { key.current = newKey(); token.current = null; confirmNetwork.current = false; setStage("review"); setPin(""); setError(null); setMismatch(null); setNeedFunds(false); }
  }, [open]);

  async function run(pinValue: string, reuse: boolean) {
    setBusy(true); setError(null); setNeedFunds(false);
    try {
      let pinToken = reuse && token.current && Date.now() - token.current.at < 90_000 ? token.current.value : null;
      if (!pinToken) {
        const r = await api.post<{ pin_token: string }>("/api/v1/auth/pin/verify", { pin: pinValue });
        pinToken = r.pin_token;
        token.current = { value: pinToken, at: Date.now() };
      }
      const txn = await submit({ pinToken, idempotencyKey: key.current, confirmNetwork: confirmNetwork.current });
      await Promise.all([qc.invalidateQueries({ queryKey: ["wallet"] }), qc.invalidateQueries({ queryKey: ["txns"] })]);
      onClose();
      navigate(`/activity/${txn.reference}`, { replace: true });
    } catch (e) {
      handle(e);
    } finally {
      setBusy(false);
    }
  }

  function handle(e: unknown) {
    setPin(""); setPinKey((k) => k + 1);
    if (!(e instanceof ApiError)) { setError(friendly(e)); return; }
    switch (e.code) {
      case "invalid_pin": setError("That PIN is incorrect."); return;
      case "pin_locked": setError(e.message); return;
      case "network_mismatch": setMismatch(e.message); setStage("review"); return;
      case "price_changed": onClose(); onPriceChanged?.(e.message); return;
      case "insufficient_funds": setNeedFunds(true); setError(e.message); return;
      case "network_error": setError("Connection problem. Your payment may have gone through: check Activity before trying again."); return; // key is kept
      default:
        if (e.status >= 500) setError(`${friendly(e)} Check Activity before trying again.`); // key is kept
        else { setError(friendly(e)); key.current = newKey(); }
    }
  }

  const noPin = !!me && !me.has_pin;
  return (
    <Sheet open={open} onClose={busy ? () => undefined : onClose} title={title}>
      <div className="stack">
        <h2>{stage === "review" ? title : "Enter your PIN"}</h2>
        {stage === "review" ? (
          <>
            <dl style={{ margin: 0 }}>{lines.map(([k, v]) => <KV key={k} k={k} v={v} />)}<KV k="You pay" v={<strong style={{ fontSize: "var(--t-lg)" }}>{total}</strong>} /></dl>
            {note && <p className="hint">{note}</p>}
            {mismatch && (
              <Banner tone="warn">
                <div className="stack-sm"><span>{mismatch}</span>
                  <Button sm variant="secondary" onClick={() => { confirmNetwork.current = true; setMismatch(null); if (token.current && Date.now() - token.current.at < 90_000) void run("", true); else setStage("pin"); }}>Yes, the number is on this network</Button>
                </div>
              </Banner>
            )}
            {noPin ? <Banner tone="warn"><span>Set a transaction PIN first. <Link to="/account/pin">Set PIN</Link></span></Banner> : null}
            <p className="hint">The amount is held from your wallet now. If the purchase fails, it is returned automatically.</p>
            <Button block disabled={noPin || !!mismatch} onClick={() => setStage("pin")}>Confirm and pay</Button>
            <Button block variant="ghost" onClick={onClose}>Cancel</Button>
          </>
        ) : (
          <>
            <p className="muted">Enter the 4-digit PIN you use for payments.</p>
            <PinPad key={pinKey} value={pin} onChange={setPin} disabled={busy} onComplete={(v) => void run(v, false)} />
            {busy && <p className="center muted small" role="status">Placing your order…</p>}
            {error && <Banner tone="error"><span>{error}{needFunds && <> <Link to="/fund">Add money</Link></>}</span></Banner>}
            <Button block variant="ghost" disabled={busy} onClick={() => { setStage("review"); setError(null); }}>Back</Button>
          </>
        )}
      </div>
    </Sheet>
  );
}
