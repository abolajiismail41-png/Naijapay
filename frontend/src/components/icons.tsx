import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };
type P = SVGProps<SVGSVGElement>;
const I = (d: string) => (p: P) => <svg {...base} {...p}><path d={d} /></svg>;

export const HomeIcon = I("M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z");
export const PayIcon = (p: P) => <svg {...base} {...p}><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M3 10h18M7 15h4" /></svg>;
export const ListIcon = I("M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01");
export const UserIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="8" r="4" /><path d="M4 20a8 8 0 0 1 16 0" /></svg>;
export const PhoneIcon = (p: P) => <svg {...base} {...p}><rect x="7" y="2.5" width="10" height="19" rx="2" /><path d="M11 18.5h2" /></svg>;
export const SignalIcon = I("M4 20v-4M9 20v-8M14 20V8M19 20V4");
export const BoltIcon = I("M13 2L5 14h6l-1 8 8-12h-6z");
export const CapIcon = I("M2 9l10-5 10 5-10 5zM6 11.5V16c0 1.5 3 3 6 3s6-1.5 6-3v-4.5");
export const PlusIcon = I("M12 5v14M5 12h14");
export const ChevIcon = I("M9 6l6 6-6 6");
export const CheckIcon = I("M5 12.5l4.5 4.5L19 7.5");
export const ClockIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
export const XIcon = I("M6 6l12 12M18 6L6 18");
export const CopyIcon = (p: P) => <svg {...base} {...p}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></svg>;
export const ShieldIcon = I("M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z");
export const BackIcon = I("M15 6l-6 6 6 6");

export const TvIcon = (p: P) => <svg {...base} {...p}><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M8 2l4 4 4-4M9 23h6" /></svg>;

export const BellIcon = I("M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4");
