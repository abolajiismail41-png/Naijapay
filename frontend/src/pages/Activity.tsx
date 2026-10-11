import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { TxnRow } from "../components/TxnRow";
import { Banner, Button, Empty, PageHead, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { formatKobo } from "../lib/money";
import type { Page, Txn, WalletEntry } from "../lib/types";

function entryTitle(e: WalletEntry): string {
  if (e.kind === "reversal") return "Refund to wallet";
  if (e.kind === "wallet.funding") return "Wallet top-up";
  if (e.kind === "dev.credit") return "Test credit";
  return e.description || "Wallet movement";
}

function useCursorList<T>(key: string[], path: string) {
  return useInfiniteQuery({
    queryKey: key, initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.get<Page<T>>(path, { limit: 20, cursor: pageParam }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export default function Activity() {
  const [tab, setTab] = useState<"purchases" | "wallet">("purchases");
  const txns = useCursorList<Txn>(["txns", "all"], "/api/v1/transactions");
  const entries = useCursorList<WalletEntry>(["wallet-entries"], "/api/v1/wallet/entries");
  const cur = tab === "purchases" ? txns : entries;
  const txnItems = txns.data?.pages.flatMap((p) => p.items) ?? [];
  const entryItems = entries.data?.pages.flatMap((p) => p.items) ?? [];
  const empty = (tab === "purchases" ? txnItems : entryItems).length === 0;
  return (
    <div className="stack">
      <PageHead title="Activity" />
      <div className="tabs" role="tablist">
        {(["purchases", "wallet"] as const).map((t) => <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t === "purchases" ? "Purchases" : "Wallet"}</button>)}
      </div>
      <div className="card flush">
        {cur.isPending ? <div className="stack" style={{ padding: "var(--s4)" }}><Skeleton h={44} /><Skeleton h={44} /><Skeleton h={44} /></div>
          : cur.isError ? <div style={{ padding: "var(--s4)" }}><Banner tone="error">{friendly(cur.error)}</Banner></div>
          : empty ? <Empty title="Nothing here yet" />
          : tab === "purchases" ? <div className="list">{txnItems.map((t) => <TxnRow key={t.reference} t={t} />)}</div>
          : <div className="list">{entryItems.map((e) => (
              <div key={e.id} className="list-row">
                <span className="grow"><span className="title">{entryTitle(e)}</span><span className="muted xs" style={{ display: "block" }}>{fmtDateTime(e.created_at)}</span></span>
                <strong className="num" style={{ color: e.type === "in" ? "var(--accent-strong)" : undefined }}>{e.type === "in" ? "+" : "−"}{formatKobo(e.amount_kobo)}</strong>
              </div>))}</div>}
      </div>
      {cur.hasNextPage && <Button variant="secondary" block loading={cur.isFetchingNextPage} onClick={() => void cur.fetchNextPage()}>Load more</Button>}
    </div>
  );
}
