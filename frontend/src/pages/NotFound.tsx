import { LinkButton } from "../components/ui";

export default function NotFound() {
  return <div className="main stack center" style={{ paddingTop: "20vh" }}><h1>Page not found</h1><p className="muted">That page does not exist.</p><LinkButton to="/home">Go home</LinkButton></div>;
}
