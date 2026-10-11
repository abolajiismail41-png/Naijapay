// One place to change the brand until the identity is final.
export const BRAND = { name: "NaijaPay", tagline: "Pay bills and top up, with a receipt for everything." };
export const API_BASE: string = import.meta.env.VITE_API_URL ?? "";
export const DEV_TOOLS: boolean = import.meta.env.VITE_DEV_TOOLS === "true";
