import { useQuery } from "@tanstack/react-query";
import { Banner, PageHead, Skeleton } from "../components/ui";
import { api, friendly } from "../lib/api";

type EsimStatus = { enabled: boolean; available: boolean; reason: string };
export default function Esim() {
  const status = useQuery({ queryKey: ["esim-status"], queryFn: () => api.get<EsimStatus>("/api/v1/esim/status"), retry: false });
  return <div className="stack"><PageHead title="Travel eSIM" sub="Mobile data plans for travel. This service is not yet available for purchase." back="/pay" />{status.isPending ? <Skeleton h={100} /> : status.isError ? <Banner tone="error">{friendly(status.error)}</Banner> : <div className="card stack-sm"><h2 className="section-title">Coming soon</h2><p>{status.data.reason}</p><p className="muted small">We will only list plans and sell eSIMs once the official provider API supports verified plan details, purchase status and activation instructions. No payment will be taken on this page.</p></div>}</div>;
}
