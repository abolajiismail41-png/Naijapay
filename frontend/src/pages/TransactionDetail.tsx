import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckIcon, ClockIcon, XIcon } from "../components/icons";
import {
  Banner,
  Button,
  CopyButton,
  KV,
  LinkButton,
  PageHead,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import Support from "../components/Support";
import { api, friendly } from "../lib/api";
import { fmtDateTime, groupDigits } from "../lib/format";
import { formatKobo } from "../lib/money";
import { label, pollInterval, txnTitle } from "../lib/txn";
import type { PinsReveal, TokenReveal, Txn } from "../lib/types";

const AGAIN: Record<string, string> = {
  AIRTIME: "/pay/airtime",
  DATA: "/pay/data",
  ELECTRICITY: "/pay/electricity",
  EDUCATION: "/pay/exam-pins",
  TV: "/pay/tv",
};

function Secret({ t }: { t: Txn }) {
  const [data, setData] = useState<TokenReveal | PinsReveal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isToken = t.service === "ELECTRICITY";

  useEffect(() => {
    if (!data) return;

    const h = setTimeout(() => setData(null), 60_000);
    return () => clearTimeout(h);
  }, [data]);

  async function reveal() {
    setBusy(true);
    setError(null);

    try {
      setData(
        await api.get<TokenReveal | PinsReveal>(
          isToken
            ? `/api/v1/electricity/${t.reference}/token`
            : `/api/v1/education/${t.reference}/pins`,
        ),
      );
    } catch (e) {
      setError(friendly(e));
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <div className="stack-sm no-print">
        <Button block loading={busy} onClick={reveal}>
          {isToken ? "Show my token" : "Show my PINs"}
        </Button>

        {error && <Banner tone="error">{error}</Banner>}
      </div>
    );
  }

  if ("token" in data) {
    return (
      <div className="stack-sm">
        <span className="section-title">Your token</span>

        <div className="secret" aria-live="polite">
          {groupDigits(data.token)}
        </div>

        {data.units && (
          <p className="muted small">{data.units} units</p>
        )}

        <div className="row no-print">
          <CopyButton text={data.token} label="Copy token" />

          <Button variant="ghost" sm onClick={() => setData(null)}>
            Hide
          </Button>
        </div>

        <p className="hint">
          Enter this token on your meter. It is hidden again after a minute.
        </p>
      </div>
    );
  }

  return (
    <div className="stack-sm">
      <span className="section-title">
        Your PINs ({data.received} of {data.ordered})
      </span>

      {data.pins.map((p, i) => (
        <div key={i} className="stack-sm">
          <div className="secret">{p.pin}</div>

          <div className="row between">
            <span className="muted small">
              Serial: <span className="mono">{p.serial}</span>
            </span>

            <span className="no-print">
              <CopyButton text={p.pin} label="Copy PIN" />
            </span>
          </div>
        </div>
      ))}

      {!data.complete && (
        <Banner tone="warn">
          We are sorting out the remaining PINs. You will see them here as
          soon as they are ready.
        </Banner>
      )}

      <Button
        variant="ghost"
        sm
        className="no-print"
        onClick={() => setData(null)}
      >
        Hide
      </Button>
    </div>
  );
}

export default function TransactionDetail() {
  const { ref = "" } = useParams();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["txn", ref],
    queryFn: () => api.get<Txn>(`/api/v1/transactions/${ref}`),
    refetchInterval: (query) => pollInterval(query.state.data),
  });

  const t = q.data;

  useEffect(() => {
    if (t && ["SUCCESSFUL", "REFUNDED", "FAILED"].includes(t.status)) {
      void qc.invalidateQueries({ queryKey: ["wallet"] });
      void qc.invalidateQueries({ queryKey: ["txns"] });
    }
  }, [t?.status, qc]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isPending) {
    return (
      <div className="stack">
        <PageHead title="Receipt" back="/activity" />
        <Skeleton h={160} />
      </div>
    );
  }

  if (q.isError || !t) {
    return (
      <div className="stack">
        <PageHead title="Receipt" back="/activity" />
        <Banner tone="error">{friendly(q.error)}</Banner>
      </div>
    );
  }

  const open = ![
    "SUCCESSFUL",
    "FAILED",
    "REFUNDED",
    "REVERSED",
  ].includes(t.status);

  const Icon =
    t.status === "SUCCESSFUL"
      ? CheckIcon
      : t.status === "FAILED" || t.status === "REFUNDED"
        ? XIcon
        : ClockIcon;

  const wantsSecret =
    t.status === "SUCCESSFUL" &&
    ((t.service === "ELECTRICITY" && t.token_available) ||
      (t.service === "EDUCATION" && t.pins_available));

  return (
    <div className="stack">
      <PageHead title="Receipt" back="/activity" />

      <section className="card stack" aria-live="polite">
        <div className="row" style={{ gap: "var(--s3)" }}>
          <span
            className="icon"
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              display: "grid",
              placeItems: "center",
              background: "var(--accent-soft)",
              color: "var(--accent-strong)",
            }}
          >
            <Icon width={24} height={24} />
          </span>

          <div className="grow">
            <h2>{txnTitle(t)}</h2>
            <StatusBadge status={t.display_status} />
          </div>

          <strong className="num" style={{ fontSize: "var(--t-lg)" }}>
            {formatKobo(t.price_kobo)}
          </strong>
        </div>

        <p>{t.message}</p>

        {t.status === "UNKNOWN" && (
          <Banner tone="warn">
            Please do not try this purchase again. We are confirming it with
            the provider and will resolve it for you.
          </Banner>
        )}

        {open && t.status !== "UNKNOWN" && (
          <p className="muted small">This page updates by itself.</p>
        )}
      </section>

      {wantsSecret && (
        <section className="card">
          <Secret t={t} />
        </section>
      )}

      <section className="card">
        <dl style={{ margin: 0 }}>
          {t.network && <KV k="Network" v={label(t.network)} />}

          {t.phone && (
            <KV k="Number" v={`0${t.phone.slice(4)}`} />
          )}

          {t.plan && (
            <KV
              k="Plan"
              v={`${t.plan}${t.validity ? ` · ${t.validity}` : ""}`}
            />
          )}

          {t.service === "AIRTIME" && (
            <KV k="Airtime value" v={formatKobo(t.amount_kobo)} />
          )}

          {t.service === "ELECTRICITY" && (
            <>
              <KV k="Company" v={t.disco ?? ""} />
              <KV
                k="Meter"
                v={`${t.meter_number ?? ""} · ${t.meter_type ?? ""}`}
              />
              <KV k="Name" v={t.customer_name ?? ""} />
              <KV k="Token value" v={formatKobo(t.amount_kobo)} />
            </>
          )}

          {t.service === "EDUCATION" && (
            <KV k="Quantity" v={String(t.quantity ?? 1)} />
          )}

          {t.service === "TV" && (
            <>
              <KV k="Provider" v={t.operator ?? "TV"} />
              <KV k="Package" v={t.product ?? ""} />
              <KV k="Smartcard" v={t.smartcard_number ?? ""} />
              <KV k="Customer" v={t.customer_name ?? ""} />

              {t.current_bouquet && (
                <KV k="Previous package" v={t.current_bouquet} />
              )}
            </>
          )}

          <KV k="Amount paid" v={formatKobo(t.price_kobo)} />
          <KV k="Date" v={fmtDateTime(t.created_at)} />

          {t.completed_at && (
            <KV k="Completed" v={fmtDateTime(t.completed_at)} />
          )}

          <KV
            k="Reference"
            v={<span className="mono xs">{t.reference}</span>}
          />
        </dl>
      </section>

      <div className="row no-print" style={{ flexWrap: "wrap" }}>
        <CopyButton text={t.reference} label="Copy reference" />

        <Button variant="secondary" sm onClick={() => window.print()}>
          Print / save receipt
        </Button>

        {typeof navigator !== "undefined" && "share" in navigator && (
          <Button
            variant="secondary"
            sm
            onClick={() =>
              void navigator
                .share({
                  title: "Receipt",
                  text: `${txnTitle(t)} ${formatKobo(t.price_kobo)}: ref ${t.reference}`,
                })
                .catch(() => undefined)
            }
          >
            Share
          </Button>
        )}
      </div>

      {AGAIN[t.service] &&
        ["SUCCESSFUL", "FAILED", "REFUNDED"].includes(t.status) && (
          <LinkButton
            to={AGAIN[t.service]!}
            variant="secondary"
            block
            className="no-print"
          >
            Buy again
          </LinkButton>
        )}

      <div className="no-print">
        <Support
          compact
          transaction={{
            reference: t.reference,
            status: t.display_status,
            service: txnTitle(t),
            amount: formatKobo(t.price_kobo),
          }}
        />
      </div>

      <p className="hint no-print">
        Need help? Your transaction reference is included in the support
        message. <Link to="/activity">Back to activity</Link>
      </p>
    </div>
  );
}