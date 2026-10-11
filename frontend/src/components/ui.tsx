import { type ButtonHTMLAttributes, type ReactNode, useState } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { useId } from "react";
import { formatKobo } from "../lib/money";
import { CopyIcon } from "./icons";

export const cls = (...parts: Array<string | false | null | undefined>): string => parts.filter(Boolean).join(" ");

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "on-dark"; block?: boolean; sm?: boolean; loading?: boolean };
export function Button({ variant = "primary", block, sm, loading, children, disabled, className, type = "button", ...rest }: BtnProps) {
  return (
    <button {...rest} type={type} disabled={disabled || loading} aria-busy={loading || undefined} className={cls("btn", variant, block && "block", sm && "sm", className)}>
      {loading && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function LinkButton({ variant = "primary", block, sm, className, ...rest }: LinkProps & { variant?: BtnProps["variant"]; block?: boolean; sm?: boolean }) {
  return <Link {...rest} className={cls("btn", variant, block && "block", sm && "sm", className)} />;
}

interface FieldProps { label: string; hint?: string; error?: string | null; children: (a: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode }
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-e` : hint ? `${id}-h` : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {error ? <div id={`${id}-e`} className="field-error" role="alert">{error}</div> : hint ? <div id={`${id}-h`} className="hint">{hint}</div> : null}
    </div>
  );
}

interface TextProps { label: string; value: string; onChange: (v: string) => void; error?: string | null; hint?: string; type?: string; inputMode?: "text" | "numeric" | "decimal" | "tel"; autoComplete?: string; placeholder?: string; maxLength?: number; autoFocus?: boolean; disabled?: boolean }
export function TextField({ label, value, onChange, error, hint, type = "text", inputMode, autoComplete, placeholder, maxLength, autoFocus, disabled }: TextProps) {
  return (
    <Field label={label} error={error} hint={hint}>
      {(a) => <input {...a} className="input" type={type} inputMode={inputMode} autoComplete={autoComplete} placeholder={placeholder} maxLength={maxLength} autoFocus={autoFocus} disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)} />}
    </Field>
  );
}

export function MoneyField({ label, value, onChange, error, hint, placeholder }: { label: string; value: string; onChange: (v: string) => void; error?: string | null; hint?: string; placeholder?: string }) {
  return (
    <Field label={label} error={error} hint={hint}>
      {(a) => (
        <div className="input-affix">
          <span aria-hidden="true">₦</span>
          <input {...a} inputMode="decimal" autoComplete="off" placeholder={placeholder ?? "0"} value={value} onChange={(e) => onChange(e.target.value.replace(/[^\d.,]/g, ""))} />
        </div>
      )}
    </Field>
  );
}

export function Banner({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  return <div className={cls("banner", tone)} role={tone === "error" ? "alert" : "status"}>{children}</div>;
}

type Tone = "ok" | "wait" | "bad" | "neutral";
const TXN_TONE: Record<string, [Tone, string]> = {
  SUCCESSFUL: ["ok", "Successful"], PROCESSING: ["wait", "Processing"], PENDING: ["wait", "Confirming"],
  FAILED: ["bad", "Failed"], REFUNDED: ["neutral", "Refunded"], REVERSED: ["neutral", "Reversed"],
  INITIATED: ["wait", "Starting"], ABANDONED: ["bad", "Not completed"], MISMATCH: ["wait", "Under review"],
};
export function StatusBadge({ status }: { status: string }) {
  const [tone, label] = TXN_TONE[status] ?? ["neutral", status];
  return <span className={cls("badge", tone)}>{label}</span>;
}

export const Spinner = () => <span className="spinner" role="status" aria-label="Loading" />;
export const Skeleton = ({ w = "100%", h = 20 }: { w?: string | number; h?: number }) => <div className="skeleton" style={{ width: w, height: h }} aria-hidden="true" />;
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children && <p className="small" style={{ marginTop: 4 }}>{children}</p>}</div>;
}
export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div className="kv"><dt>{k}</dt><dd>{v}</dd></div>;
}
export function Money({ kobo }: { kobo: number }) {
  return <span className="num">{formatKobo(kobo)}</span>;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button variant="secondary" sm onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ } }}>
      <CopyIcon width={16} height={16} /> {done ? "Copied" : label}
    </Button>
  );
}

export function PageHead({ title, sub, back }: { title: string; sub?: string; back?: string }) {
  return (
    <header className="stack-sm" style={{ marginBottom: "var(--s4)" }}>
      {back && <Link to={back} className="small" style={{ textDecoration: "none" }}>← Back</Link>}
      <h1>{title}</h1>
      {sub && <p className="muted">{sub}</p>}
    </header>
  );
}
