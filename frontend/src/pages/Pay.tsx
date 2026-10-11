import { PageHead } from "../components/ui";
import { ServiceList } from "./Home";

export default function Pay() {
  return <div className="stack"><PageHead title="What do you want to pay for?" /><ServiceList /></div>;
}
