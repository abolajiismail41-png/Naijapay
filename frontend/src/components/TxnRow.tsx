import { Link } from "react-router-dom";
import { fmtDateTime } from "../lib/format";
import { formatKobo } from "../lib/money";
import { txnTitle } from "../lib/txn";
import type { Txn } from "../lib/types";
import { BoltIcon, CapIcon, ChevIcon, PhoneIcon, SignalIcon } from "./icons";
import { StatusBadge } from "./ui";

const ICONS: Record<string, typeof PhoneIcon> = { AIRTIME: PhoneIcon, DATA: SignalIcon, ELECTRICITY: BoltIcon, EDUCATION: CapIcon };

export function TxnRow({ t }: { t: Txn }) {
  const Icon = ICONS[t.service] ?? PhoneIcon;
  return (
    <Link to={`/activity/${t.reference}`} className="list-row">
      <span className="icon"><Icon /></span>
      <span className="grow">
        <span className="title">{txnTitle(t)}</span>
        <span className="muted xs" style={{ display: "block" }}>{fmtDateTime(t.created_at)}</span>
      </span>
      <span className="right">
        <span className="num" style={{ display: "block", fontWeight: 600 }}>{formatKobo(t.price_kobo)}</span>
        <StatusBadge status={t.display_status} />
      </span>
      <ChevIcon className="chev" />
    </Link>
  );
}
