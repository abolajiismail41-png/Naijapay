import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Banner, PageHead } from "../components/ui";
import { FINANCE_ROLES, STAFF_ROLES } from "../lib/types";

export function AdminIndex() {
  const { me } = useAuth();
  return <Navigate to={me && FINANCE_ROLES.includes(me.role) ? "/admin/profit" : "/admin/overview"} replace />;
}

export default function AdminLayout() {
  const { me } = useAuth();
  if (!me || !STAFF_ROLES.includes(me.role)) return <Banner tone="warn">You do not have access to this area.</Banner>;
  const finance = FINANCE_ROLES.includes(me.role);
  const userOps = ["SUPPORT", "ADMIN", "SUPER_ADMIN"].includes(me.role);
  return (
    <div className="stack">
      <PageHead title="Admin" sub={`Signed in as ${me.role.replace("_", " ").toLowerCase()}. The server enforces every permission.`} />
      <nav className="tabs" aria-label="Admin sections">
        {finance && <NavLink className="tab" to="/admin/profit">Profit</NavLink>}
        {finance && <NavLink className="tab" to="/admin/pricing">Pricing</NavLink>}
        {finance && <NavLink className="tab" to="/admin/catalogue">Catalogue</NavLink>}
        {(me.role === "ADMIN" || me.role === "SUPER_ADMIN" || finance) && <NavLink className="tab" to="/admin/virtual-numbers">Virtual Numbers & eSIM</NavLink>}
        {userOps && <NavLink className="tab" to="/admin/overview">Overview</NavLink>}
        {userOps && <NavLink className="tab" to="/admin/users">Users</NavLink>}
        {finance && <NavLink className="tab" to="/admin/promotions">Promotions</NavLink>}
        {(finance || me.role === "ADMIN" || me.role === "SUPER_ADMIN") && <NavLink className="tab" to="/admin/risk">Fraud & reconciliation</NavLink>}
        <NavLink className="tab" to="/admin/transactions">Transactions</NavLink>
        {(me.role === "ADMIN" || me.role === "SUPER_ADMIN") && <NavLink className="tab" to="/admin/audit">Audit log</NavLink>}
      </nav>
      <Outlet />
    </div>
  );
}
