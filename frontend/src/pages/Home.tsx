import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ChevIcon, PlusIcon } from "../components/icons";
import { TxnRow } from "../components/TxnRow";
import Support from "../components/Support";
import { Banner, Empty, LinkButton, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";
import { firstName } from "../lib/format";
import { formatKobo } from "../lib/money";
import type { Page, Txn, Wallet } from "../lib/types";
import { SERVICES } from "./services";

export function WalletCard() {
  const q = useQuery({
    queryKey: ["wallet"],
    queryFn: () => api.get<Wallet>("/api/v1/wallet"),
    refetchOnWindowFocus: true,
  });

  return (
    <section className="wallet-card" aria-label="Wallet balance">
      <div className="label">Wallet balance</div>

      <div className="amount num" aria-live="polite">
        {q.data ? (
          formatKobo(q.data.balance_kobo)
        ) : q.isError ? (
          "—"
        ) : (
          <Skeleton w={180} h={38} />
        )}
      </div>

      {q.isError && (
        <p className="small" role="alert">
          {friendly(q.error)}
        </p>
      )}

      <LinkButton to="/fund" variant="on-dark" sm>
        <PlusIcon width={18} height={18} />
        Add money
      </LinkButton>
    </section>
  );
}

export function ServiceList() {
  return (
    <div className="card service-panel">
      <div className="service-grid">
        {SERVICES.map(({ key, title, sub, to, Icon }) => (
          <Link key={key} to={to} className="service-tile">
            <span className="icon">
              <Icon />
            </span>

            <span className="grow">
              <span className="title">{title}</span>
              <span className="muted small service-sub">{sub}</span>
            </span>

            <ChevIcon className="chev" />
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function Home() {
  const { me } = useAuth();

  const recent = useQuery({
    queryKey: ["txns", "recent"],
    queryFn: () => api.get<Page<Txn>>("/api/v1/transactions", { limit: 5 }),
  });

  return (
    <div className="stack">
      <header>
        <p className="muted">Hello,</p>
        <h1>{me ? firstName(me.full_name) : ""}</h1>
      </header>

      <WalletCard />

      {me && !me.has_pin && (
        <Banner tone="warn">
          <span>
            Set a transaction PIN to start paying.{" "}
            <Link to="/account/pin">Set PIN</Link>
          </span>
        </Banner>
      )}

      <section className="stack-sm">
        <h2 className="section-title">Pay for</h2>
        <ServiceList />
      </section>

      <section className="stack-sm">
        <div className="row between">
          <h2 className="section-title">Recent activity</h2>
          <Link to="/activity" className="small">
            See all
          </Link>
        </div>

        <div className="card flush">
          {recent.isPending ? (
            <div className="stack" style={{ padding: "var(--s4)" }}>
              <Skeleton h={44} />
              <Skeleton h={44} />
            </div>
          ) : recent.isError ? (
            <div style={{ padding: "var(--s4)" }}>
              <Banner tone="error">{friendly(recent.error)}</Banner>
            </div>
          ) : recent.data.items.length === 0 ? (
            <Empty title="No purchases yet">
              Your payments will show up here.
            </Empty>
          ) : (
            <div className="list">
              {recent.data.items.map((t) => (
                <TxnRow key={t.reference} t={t} />
              ))}
            </div>
          )}
        </div>
      </section>

      <Support />
    </div>
  );
}