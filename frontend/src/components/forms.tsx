import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { normalizePhone, toLocalPhone } from "../lib/phone";
import { Button, Field } from "./ui";

export function usePhone(initial = "") {
  const [raw, setRaw] = useState(initial);
  const e164 = normalizePhone(raw);
  return { raw, setRaw, e164, valid: e164 !== null, error: raw && !e164 ? "Enter a valid Nigerian number, e.g. 0803 123 4567" : null };
}

export function PhoneField({ label = "Phone number", raw, onChange, error }: { label?: string; raw: string; onChange: (v: string) => void; error?: string | null }) {
  const { me } = useAuth();
  return (
    <Field label={label} error={error}>
      {(a) => (
        <div className="row">
          <input {...a} className="input grow" inputMode="tel" autoComplete="tel" placeholder="0803 123 4567" value={raw} onChange={(e) => onChange(e.target.value)} />
          {me && <Button variant="secondary" sm onClick={() => onChange(toLocalPhone(me.phone))}>My number</Button>}
        </div>
      )}
    </Field>
  );
}

export function Chips({ options, value, onChange, label }: { options: Array<{ key: string; text: string }>; value: string; onChange: (k: string) => void; label: string }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {options.map((o) => <button key={o.key} type="button" className="chip" aria-pressed={value === o.key} onClick={() => onChange(o.key)}>{o.text}</button>)}
    </div>
  );
}

export function Segmented({ options, value, onChange, label }: { options: Array<{ key: string; text: string }>; value: string; onChange: (k: string) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={o.key} type="button" aria-pressed={value === o.key} onClick={() => onChange(o.key)}>{o.text}</button>)}
    </div>
  );
}
