const NATIONAL = /^[789][01]\d{8}$/;

/** Mirrors the backend rule; returns +234XXXXXXXXXX or null. */
export function normalizePhone(raw: string): string | null {
  const digits = raw.replace(/[\s\-()]/g, "");
  let national: string;
  if (digits.startsWith("+234")) national = digits.slice(4);
  else if (digits.startsWith("234")) national = digits.slice(3);
  else if (digits.startsWith("0")) national = digits.slice(1);
  else return null;
  return NATIONAL.test(national) ? `+234${national}` : null;
}

export const toLocalPhone = (e164: string): string => `0${e164.slice(4)}`;
