const dateTime = new Intl.DateTimeFormat("en-NG", { dateStyle: "medium", timeStyle: "short", timeZone: "Africa/Lagos" });
const dateOnly = new Intl.DateTimeFormat("en-NG", { dateStyle: "medium", timeZone: "Africa/Lagos" });

export const fmtDateTime = (iso: string): string => dateTime.format(new Date(iso));
export const fmtDate = (iso: string): string => dateOnly.format(new Date(iso));
export const firstName = (full: string): string => full.trim().split(/\s+/)[0] ?? full;

export function groupDigits(value: string): string {
  return value.replace(/\s+/g, "").replace(/(.{4})/g, "$1 ").trim();
}

export function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
}
