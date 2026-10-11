import type { Txn } from "./types";

export function txnTitle(t: Txn): string {
  switch (t.service) {
    case "AIRTIME": return `${label(t.network)} airtime`;
    case "DATA": return `${label(t.network)} ${t.plan ?? "data"}`;
    case "ELECTRICITY": return `${t.disco ?? "Electricity"} ${t.meter_type ? t.meter_type.toLowerCase() : ""}`.trim();
    case "EDUCATION": return `${t.product ?? "Exam PIN"}${t.quantity && t.quantity > 1 ? ` ×${t.quantity}` : ""}`;
    case "TV": return `${t.operator ?? "TV"} ${t.product ?? "subscription"}`;
    default: return t.service;
  }
}
const NAMES: Record<string, string> = { MTN: "MTN", AIRTEL: "Airtel", GLO: "Glo", "9MOBILE": "9mobile" };
export const label = (n: string | null): string => (n ? (NAMES[n] ?? n) : "");
export const networkLabel = label;

export const TERMINAL: string[] = ["SUCCESSFUL", "FAILED", "REFUNDED", "REVERSED"];

/** Poll while the outcome is open, and while a delivered secret (token / PINs) is still being retrieved. */
export function pollInterval(t: Txn | undefined): number | false {
  if (!t) return 3000;
  if (!TERMINAL.includes(t.status)) return t.status === "UNKNOWN" ? 10_000 : 2500;
  if (t.status === "SUCCESSFUL") {
    if (t.service === "ELECTRICITY" && t.meter_type === "PREPAID" && !t.token_available) return 15_000;
    if (t.service === "EDUCATION" && !t.pins_available) return 15_000;
  }
  return false;
}
