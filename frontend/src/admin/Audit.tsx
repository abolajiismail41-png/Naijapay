import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Banner,
  Button,
  Skeleton,
  TextField,
} from "../components/ui";
import { api, friendly } from "../lib/api";
import { fmtDateTime } from "../lib/format";
interface AuditItem {
  id: string;
  created_at: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip: string | null;
  request_id: string | null;
  before: unknown;
  after: unknown;
  meta: unknown;
}
interface Page {
  items: AuditItem[];
  next_cursor: string | null;
}
export default function AuditPage() {
  const [action, setAction] = useState("");
  const [resource, setResource] = useState("");
  const [filters, setFilters] = useState({
    action: "",
    resource: "",
  });
  const q = useQuery({
    queryKey: ["admin-audit", filters],
    queryFn: () =>
      api.get<Page>("/api/v1/admin/audit", {
        action: filters.action || undefined,
        resource_type: filters.resource || undefined,
        limit: 50,
      }),
  });
  const errorMessage = q.isError
    ? String(friendly(q.error) || "Unable to load audit events.")
    : "";
  return (
    <div className="stack">
      <form
        className="row"
        style={{ alignItems: "end", flexWrap: "wrap" }}
        onSubmit={(event) => {
          event.preventDefault();
          setFilters({
            action: action.trim(),
            resource: resource.trim(),
          });
        }}
      >
        <div className="grow">
          <TextField
            label="Exact action"
            value={action}
            onChange={setAction}
            placeholder="admin.user_status_changed"
          />
        </div>
        <div className="grow">
          <TextField
            label="Resource type"
            value={resource}
            onChange={setResource}
            placeholder="user, transaction, promotion"
          />
        </div>
        <Button type="submit">Filter</Button>
      </form>
      <p className="muted small">
        Read-only audit trail. Entries are not editable through this
        interface.
      </p>
      {q.isError && (
        <Banner tone="error">{errorMessage}</Banner>
      )}
      {q.isPending ? (
        <Skeleton h={180} />
      ) : q.data?.items.length ? (
        <div className="stack-sm">
          {q.data.items.map((item) => {
            const hasChangeDetails = Boolean(
              item.before || item.after || item.meta,
            );
            return (
              <article className="card stack-sm" key={item.id}>
                <div
                  className="row between"
                  style={{ alignItems: "start" }}
                >
                  <div>
                    <strong>{item.action}</strong>
                    <div className="muted xs">
                      {fmtDateTime(item.created_at)}
                    </div>
                  </div>
                  <span className="badge neutral">
                    {item.resource_type ?? "system"}
                  </span>
                </div>
                <dl style={{ margin: 0 }}>
                  <div className="kv">
                    <dt>Actor</dt>
                    <dd className="mono xs">
                      {item.actor_user_id ?? "System"}
                    </dd>
                  </div>
                  <div className="kv">
                    <dt>Resource</dt>
                    <dd>{item.resource_id ?? "—"}</dd>
                  </div>
                  <div className="kv">
                    <dt>IP / request</dt>
                    <dd className="mono xs">
                      {item.ip ?? "—"} / {item.request_id ?? "—"}
                    </dd>
                  </div>
                </dl>
                {hasChangeDetails && (
                  <details>
                    <summary>Change details</summary>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        overflowWrap: "anywhere",
                        fontSize: "var(--t-xs)",
                      }}
                    >
                      {JSON.stringify(
                        {
                          before: item.before,
                          after: item.after,
                          meta: item.meta,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="card empty">
          No audit events match those filters.
        </div>
      )}
    </div>
  );
}