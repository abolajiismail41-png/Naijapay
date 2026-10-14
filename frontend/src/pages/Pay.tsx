import { Link } from "react-router-dom";
import { PageHead } from "../components/ui";
import { ServiceList } from "./Home";

export default function Pay() {
  return <div className="stack"><PageHead title="What do you want to pay for?" /><ServiceList /><section className="stack-sm"><h2 className="section-title">More services</h2><div className="card flush list"><Link className="list-row" to="/pay/virtual-numbers"><span className="grow"><strong className="title">Virtual Numbers</strong><span className="muted small" style={{ display: "block" }}>SMS verification numbers</span></span><span aria-hidden="true">→</span></Link><Link className="list-row" to="/pay/esim"><span className="grow"><strong className="title">Travel eSIM</strong><span className="muted small" style={{ display: "block" }}>International mobile data · coming soon</span></span><span aria-hidden="true">→</span></Link></div></section></div>;
}
