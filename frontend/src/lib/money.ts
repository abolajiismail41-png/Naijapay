/** All money is integer kobo. These helpers never use floating-point arithmetic on amounts. */

export function formatKobo(kobo: number): string {
  const neg = kobo < 0;
  const abs = Math.abs(Math.trunc(kobo));
  const whole = Math.trunc(abs / 100);
  const frac = String(abs % 100).padStart(2, "0");
  return `${neg ? "-" : ""}₦${whole.toLocaleString("en-NG")}.${frac}`;
}

/** "₦5,000" when whole naira, otherwise with kobo. */
export function formatKoboShort(kobo: number): string {
  return kobo % 100 === 0 ? formatKobo(kobo).replace(/\.00$/, "") : formatKobo(kobo);
}

/**
 * Parse a decimal string into an integer scaled by 10^decimals ("5,000.5" -> 500050 with 2 decimals).
 * Returns null for anything that is not a plain non-negative number with at most `decimals` places.
 */
export function parseScaled(input: string, decimals = 2): number | null {
  const clean = input.replace(/[,\s₦]/g, "");
  const m = new RegExp(`^(\\d+)(?:\\.(\\d{1,${decimals}}))?$`).exec(clean);
  if (!m) return null;
  const whole = m[1] ?? "0";
  const frac = (m[2] ?? "").padEnd(decimals, "0");
  const value = Number(whole) * 10 ** decimals + Number(frac || "0");
  return Number.isSafeInteger(value) ? value : null;
}

export const parseNairaToKobo = (input: string): number | null => parseScaled(input, 2);
