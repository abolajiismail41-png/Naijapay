import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "../auth/AuthContext";
import { BRAND } from "../config";
import { STAFF_ROLES } from "../lib/types";
import {
  BellIcon,
  HomeIcon,
  ListIcon,
  PayIcon,
  ShieldIcon,
  UserIcon,
} from "./icons";
import { Spinner } from "./ui";

const items = [
  { to: "/home", label: "Home", Icon: HomeIcon },
  { to: "/pay", label: "Pay", Icon: PayIcon },
  { to: "/activity", label: "Activity", Icon: ListIcon },
  { to: "/notifications", label: "Alerts", Icon: BellIcon },
  { to: "/support", label: "Support", Icon: null },
  { to: "/account", label: "Account", Icon: UserIcon },
];

export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        N
      </span>
      {BRAND.name}
    </span>
  );
}

export function RequireAuth() {
  const { status } = useAuth();
  const loc = useLocation();

  if (status === "loading") {
    return (
      <div className="main center" style={{ paddingTop: "30vh" }}>
        <Spinner />
      </div>
    );
  }

  if (status === "anon") {
    return (
      <Navigate
        to="/login"
        state={{ from: loc.pathname }}
        replace
      />
    );
  }

  return <AppShell />;
}

function AppShell() {
  const { me } = useAuth();
  const staff = !!me && STAFF_ROLES.includes(me.role);
  const loc = useLocation();
  const wide = loc.pathname.startsWith("/admin");

  // Keep route changes predictable on mobile and move keyboard focus to the new page.
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [loc.pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <nav className="rail" aria-label="Main">
        <Brand />

        {items.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className="nav-item">
            {Icon ? (
              <Icon />
            ) : (
              <span className="support-nav-icon" aria-hidden="true">
                ?
              </span>
            )}
            {label}
          </NavLink>
        ))}

        {staff && (
          <NavLink to="/admin" className="nav-item">
            <ShieldIcon />
            Admin
          </NavLink>
        )}
      </nav>

      <main
        className={wide ? "main wide" : "main"}
        id="main"
        tabIndex={-1}
      >
        <Outlet />
      </main>

      <nav className="bottom-nav" aria-label="Main">
        {items.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className="nav-item">
            {Icon ? (
              <Icon />
            ) : (
              <span className="support-nav-icon" aria-hidden="true">
                ?
              </span>
            )}
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}