export type Role = "USER" | "SUPPORT" | "FINANCE" | "ADMIN" | "SUPER_ADMIN";
export const STAFF_ROLES: Role[] = ["SUPPORT", "FINANCE", "ADMIN", "SUPER_ADMIN"];
export const FINANCE_ROLES: Role[] = ["FINANCE", "SUPER_ADMIN"];

export interface Me { id: string; phone: string; full_name: string; email: string | null; role: Role; has_pin: boolean }
export interface Wallet { balance_kobo: number; balance: string; currency: string; status: string }
export interface Page<T> { items: T[]; next_cursor: string | null }

export type TxnStatus = "INITIATED" | "PENDING" | "PROCESSING" | "SUCCESSFUL" | "FAILED" | "UNKNOWN" | "REFUNDED" | "REVERSED";
export interface Txn {
  reference: string; service: "AIRTIME" | "DATA" | "ELECTRICITY" | "EDUCATION" | string;
  status: TxnStatus; display_status: string; message: string;
  amount_kobo: number; amount: string; price_kobo: number; price: string; currency: string;
  network: string | null; phone: string | null; plan: string | null; validity: string | null;
  created_at: string; completed_at: string | null;
  disco?: string; meter_type?: string; meter_number?: string; customer_name?: string; token_available?: boolean;
  product?: string; quantity?: number; pins_available?: boolean;
  operator?: string; smartcard_number?: string; current_bouquet?: string;
}
export interface WalletEntry { id: string; type: "in" | "out"; amount_kobo: number; amount: string; kind: string; description: string; created_at: string }

export type FundingStatus = "INITIATED" | "PENDING" | "SUCCESSFUL" | "FAILED" | "ABANDONED" | "MISMATCH";
export interface FundingQuote { amount_kobo: number; fee_kobo: number; total_kobo: number; amount: string; fee: string; total: string; min_kobo: number; max_kobo: number }
export interface Funding {
  reference: string; status: FundingStatus; message: string; amount_kobo: number; fee_kobo: number; total_kobo: number;
  currency: string; authorization_url: string | null; created_at: string | null; paid_at: string | null;
}

export type Network = "MTN" | "AIRTEL" | "GLO" | "9MOBILE";
export interface PriceQuote { price_kobo: number; price: string; amount_kobo?: number; amount?: string }
export interface DataPlan { id: string; network: Network; name: string; type: string; validity: string; price_kobo: number; price: string }
export interface Disco { id: string; code: string; name: string; meter_types: Array<"PREPAID" | "POSTPAID">; min_kobo: number; max_kobo: number }
export interface MeterValidation { validation_id: string; disco: string; meter_type: string; meter_number: string; customer_name: string; address: string; min_kobo: number; expires_in_s: number }
export interface ElectricityQuote { amount_kobo: number; amount: string; service_fee_kobo: number; service_fee: string; price_kobo: number; price: string; meter_number: string; customer_name: string }
export interface ExamProduct { id: string; code: string; name: string; max_quantity: number; unit_price_kobo: number; unit_price: string }
export interface ExamQuote { product: string; quantity: number; unit_price_kobo: number; unit_price: string; price_kobo: number; price: string }
export interface TokenReveal { token: string; units: string | null; meter_number: string; disco: string }
export interface PinsReveal { product: string; ordered: number; received: number; complete: boolean; pins: Array<{ pin: string; serial: string }> }
export interface SessionRow { id: string; device: string | null; ip: string | null; created_at: string; current: boolean }

export interface TVOperator { code: string; name: string }
export interface TVPlan { id: string; operator_code: string; operator: string; name: string; price_kobo: number; price: string }
export interface TVValidation { validation_id: string; operator_code: string; operator: string; smartcard_number: string; customer_name: string; current_bouquet: string; expires_in_s: number }
export interface TVQuote { product_id: string; operator: string; product: string; customer_name: string; smartcard_number: string; price_kobo: number; price: string }
