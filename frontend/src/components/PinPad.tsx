import { useEffect, useRef } from "react";
import { cls } from "./ui";

export function PinPad({ value, onChange, onComplete, disabled, label = "Transaction PIN" }: { value: string; onChange: (v: string) => void; onComplete?: (v: string) => void; disabled?: boolean; label?: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return (
    <div className="pin" onClick={() => ref.current?.focus()}>
      <input
        ref={ref} aria-label={label} type="password" inputMode="numeric" autoComplete="off" pattern="[0-9]*" maxLength={4}
        value={value} disabled={disabled}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 4); onChange(v); if (v.length === 4) onComplete?.(v); }}
      />
      {[0, 1, 2, 3].map((i) => <span key={i} className={cls("pin-dot", i < value.length && "on", i === value.length && "cur")} />)}
    </div>
  );
}
