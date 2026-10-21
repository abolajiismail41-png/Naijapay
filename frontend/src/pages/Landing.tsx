import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  Check,
  CreditCard,
  GraduationCap,
  Lightbulb,
  LockKeyhole,
  Menu,
  ShieldCheck,
  Smartphone,
  Tv,
  Wallet,
  Wifi,
  X,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Layout";
import { BRAND } from "../config";
import "./landing.css";

const services = [
  { title: "Airtime", text: "Recharge your phone in seconds.", icon: Smartphone },
  { title: "Mobile data", text: "Stay connected with data bundles.", icon: Wifi },
  { title: "Electricity", text: "Pay your electricity bills.", icon: Lightbulb },
  { title: "TV subscriptions", text: "Keep your favourite channels on.", icon: Tv },
  { title: "Exam PINs", text: "Purchase supported exam PINs.", icon: GraduationCap },
  { title: "Wallet funding", text: "Add money to your wallet securely.", icon: Wallet },
];

const benefits = [
  {
    title: "Secure payments",
    text: "Protected account access and appropriate security checks for sensitive transactions.",
    icon: ShieldCheck,
  },
  {
    title: "Clear transaction records",
    text: "Keep track of transaction references, payment status and purchase history.",
    icon: CreditCard,
  },
  {
    title: "One account",
    text: "Manage supported everyday digital services without switching between apps.",
    icon: Smartphone,
  },
];

const steps = [
  {
    title: "Create your account",
    text: "Register with your details and securely access your NaijaPay account.",
  },
  {
    title: "Fund your wallet",
    text: "Use the available funding options to add money to your wallet.",
  },
  {
    title: "Choose a service",
    text: "Select a supported service, enter the required details and review your payment.",
  },
];

const navLinks = [
  { href: "#services", label: "Services" },
  { href: "#benefits", label: "Why NaijaPay" },
  { href: "#how-it-works", label: "How it works" },
];

function PhonePreview() {
  return (
    <div className="np-phone" role="img" aria-label="Preview of an airtime purchase in NaijaPay">
      <div className="np-phone-notch" />
      <div className="np-phone-body">
        <div className="np-phone-top">
          <span>Wallet balance</span>
          <strong>₦24,500.00</strong>
        </div>
        <div className="np-phone-tabs">
          <span className="is-on">Airtime</span>
          <span>Data</span>
          <span>Bills</span>
        </div>
        <div className="np-field">
          <small>Phone number</small>
          <b>0803 000 0000</b>
        </div>
        <div className="np-field">
          <small>Amount</small>
          <b>₦2,000</b>
        </div>
        <div className="np-phone-pay">Pay ₦2,000</div>
      </div>
      <div className="np-sheet">
        <div className="np-sheet-check">
          <Check size={22} strokeWidth={3} />
        </div>
        <strong>Airtime sent</strong>
        <span>₦2,000 · Successful</span>
        <div className="np-sheet-ref">
          <small>Reference</small>
          <b>NP-48213907</b>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const { status } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  if (status === "authed") return <Navigate to="/home" replace />;

  if (status === "loading") {
    return (
      <div className="np np-loading">
        <span className="np-spinner" role="status" aria-label="Checking your session" />
      </div>
    );
  }

  const close = () => setMenuOpen(false);

  return (
    <div className="np">
      <header className="np-header">
        <div className="np-wrap np-header-row">
          <a href="#top" className="np-brand" aria-label={`${BRAND.name} homepage`} onClick={close}>
            <Brand />
          </a>
          <nav className="np-nav" aria-label="Main navigation">
            {navLinks.map((l) => (
              <a key={l.href} href={l.href}>
                {l.label}
              </a>
            ))}
          </nav>
          <div className="np-header-actions">
            <Link to="/login" className="np-link np-desktop-only">
              Log in
            </Link>
            <Link to="/register" className="np-btn np-btn-green np-btn-sm">
              Get started
            </Link>
            <button
              type="button"
              className="np-menu-btn"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="np-mobile-nav"
              onClick={() => setMenuOpen((o) => !o)}
            >
              {menuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="np-mobile-nav" className="np-mobile-nav" aria-label="Mobile navigation">
            {navLinks.map((l) => (
              <a key={l.href} href={l.href} onClick={close}>
                {l.label}
              </a>
            ))}
            <Link to="/login" onClick={close}>
              Log in
            </Link>
          </nav>
        )}
      </header>

      <main id="top">
        <section className="np-hero">
          <div className="np-wrap np-hero-grid">
            <div className="np-hero-copy">
              <h1 className="np-rise" style={{ "--d": "0ms" }}>
                Airtime, data, light and TV. Paid from one account.
              </h1>
              <p className="np-lead np-rise" style={{ "--d": "100ms" }}>
                Buy airtime and data, pay electricity bills, renew TV subscriptions and purchase
                supported exam PINs from one convenient account.
              </p>
              <div className="np-hero-cta np-rise" style={{ "--d": "200ms" }}>
                <Link to="/register" className="np-btn np-btn-amber">
                  Create your account
                </Link>
                <Link to="/login" className="np-btn np-btn-ghost">
                  Log in
                </Link>
              </div>
              <p className="np-hero-note np-rise" style={{ "--d": "300ms" }}>
                <LockKeyhole size={16} aria-hidden="true" />
                Account security checks on sensitive transactions
              </p>
            </div>
            <div className="np-hero-visual np-rise" style={{ "--d": "250ms" }}>
              <PhonePreview />
            </div>
          </div>
        </section>

        <section id="services" className="np-section" aria-labelledby="np-services-h">
          <div className="np-wrap">
            <div className="np-head">
              <h2 id="np-services-h">What you can pay for</h2>
              <p>
                Access supported digital services through a single account instead of juggling
                multiple payment experiences.
              </p>
            </div>
            <ul className="np-services">
              {services.map(({ title, text, icon: Icon }) => (
                <li key={title}>
                  <Link to="/register" className="np-service" aria-label={`${title}: get started`}>
                    <span className="np-ico">
                      <Icon size={22} aria-hidden="true" />
                    </span>
                    <span className="np-service-text">
                      <strong>{title}</strong>
                      <span>{text}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="benefits" className="np-section np-tint" aria-labelledby="np-benefits-h">
          <div className="np-wrap np-split">
            <div className="np-head np-head-left">
              <h2 id="np-benefits-h">Payments that keep you in control</h2>
              <p>
                A more organised way to manage supported purchases, monitor transactions and reach
                your account when you need it.
              </p>
              <Link to="/register" className="np-btn np-btn-green">
                Open your account
              </Link>
            </div>
            <ul className="np-benefits">
              {benefits.map(({ title, text, icon: Icon }) => (
                <li key={title}>
                  <span className="np-ico np-ico-solid">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <div>
                    <h3>{title}</h3>
                    <p>{text}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="how-it-works" className="np-section" aria-labelledby="np-steps-h">
          <div className="np-wrap">
            <div className="np-head">
              <h2 id="np-steps-h">Start in three steps</h2>
              <p>
                Create an account, fund your wallet using an available payment method, then choose
                the service you need.
              </p>
            </div>
            <ol className="np-steps">
              {steps.map((s, i) => (
                <li key={s.title}>
                  <span className="np-step-n" aria-hidden="true">
                    {i + 1}
                  </span>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="np-section np-section-tight">
          <div className="np-wrap">
            <div className="np-cta">
              <div>
                <h2>Ready to simplify your payments?</h2>
                <p>
                  Create your account to explore the supported services and payment options
                  available to you.
                </p>
              </div>
              <div className="np-cta-actions">
                <Link to="/register" className="np-btn np-btn-amber">
                  Create account
                </Link>
                <Link to="/login" className="np-btn np-btn-ghost">
                  Log in
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="np-footer">
        <div className="np-wrap np-footer-row">
          <div className="np-footer-brand">
            <a href="#top" aria-label={`${BRAND.name} homepage`}>
              <Brand />
            </a>
            <p>A convenient way to access supported digital payments and everyday services.</p>
          </div>
          <nav className="np-footer-links" aria-label="Footer navigation">
            {navLinks.map((l) => (
              <a key={l.href} href={l.href}>
                {l.label}
              </a>
            ))}
            <Link to="/login">Log in</Link>
            <Link to="/register">Register</Link>
          </nav>
        </div>
        <div className="np-wrap np-copy">
          © {new Date().getFullYear()} {BRAND.name}
        </div>
      </footer>
    </div>
  );
}
