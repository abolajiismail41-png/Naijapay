import { useState } from "react";
import { Navigate } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CreditCard,
  GraduationCap,
  Lightbulb,
  LockKeyhole,
  Menu,
  ShieldCheck,
  Smartphone,
  Tv,
  Wallet,
  Zap,
  X,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Layout";
import { LinkButton } from "../components/ui";
import { BRAND } from "../config";
import Hero from "../scene/Hero";
const services = [
  {
    title: "Airtime",
    description: "Recharge your phone in seconds.",
    icon: Smartphone,
  },
  {
    title: "Mobile data",
    description: "Stay connected with data bundles.",
    icon: Zap,
  },
  {
    title: "Electricity",
    description: "Pay your electricity bills.",
    icon: Lightbulb,
  },
  {
    title: "TV subscriptions",
    description: "Keep your favourite channels on.",
    icon: Tv,
  },
  {
    title: "Exam PINs",
    description: "Purchase supported exam PINs.",
    icon: GraduationCap,
  },
  {
    title: "Wallet funding",
    description: "Add money to your wallet securely.",
    icon: Wallet,
  },
];
const benefits = [
  {
    title: "Secure payments",
    description:
      "Protected account access and appropriate security checks for sensitive transactions.",
    icon: ShieldCheck,
  },
  {
    title: "Clear transaction records",
    description:
      "Keep track of transaction references, payment status and purchase history.",
    icon: CreditCard,
  },
  {
    title: "Convenient payments",
    description:
      "Manage supported everyday digital services from one account.",
    icon: Smartphone,
  },
];
const steps = [
  {
    number: "01",
    title: "Create your account",
    description:
      "Register with your details and securely access your NaijaPay account.",
    icon: Smartphone,
  },
  {
    number: "02",
    title: "Fund your wallet",
    description:
      "Use the available funding options to add money to your wallet.",
    icon: Wallet,
  },
  {
    number: "03",
    title: "Choose a service",
    description:
      "Select a supported service, enter the required details and review your payment.",
    icon: CreditCard,
  },
];
export default function Landing() {
  const { status } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  // Authenticated customers should go straight to their dashboard.
  if (status === "authed") {
    return <Navigate to="/home" replace />;
  }
  // Do not briefly show the public page while authentication is unresolved.
  if (status === "loading") {
    return (
      <div
        className="land"
        style={{
          minHeight: "100dvh",
          display: "grid",
          placeItems: "center",
        }}
      >
        <span
          role="status"
          aria-label="Checking your session"
          style={{
            width: 28,
            height: 28,
            border: "3px solid #d7f0e1",
            borderTopColor: "#07884f",
            borderRadius: "50%",
            animation: "spin 0.7s linear infinite",
          }}
        />
      </div>
    );
  }
  return (
    <div className="land">
      {/* Header */}
      <header className="land-header">
        <div className="land-header-inner">
          <a
            href="#top"
            className="land-brand"
            aria-label={`${BRAND.name} homepage`}
            onClick={() => setMenuOpen(false)}
          >
            <Brand />
          </a>
          <nav className="land-nav" aria-label="Main navigation">
            <a href="#services">Services</a>
            <a href="#benefits">Why NaijaPay</a>
            <a href="#how-it-works">How it works</a>
          </nav>
          <div className="land-actions">
            <LinkButton to="/login" variant="secondary" sm>
              Log in
            </LinkButton>
            <LinkButton to="/register" sm>
              Get started
            </LinkButton>
            <button
              type="button"
              className="land-menu-toggle"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="land-mobile-nav"
              onClick={() => setMenuOpen((open) => !open)}
            >
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav
            id="land-mobile-nav"
            className="land-mobile-nav"
            aria-label="Mobile navigation"
          >
            <a href="#services" onClick={() => setMenuOpen(false)}>
              Services <ArrowRight size={16} />
            </a>
            <a href="#benefits" onClick={() => setMenuOpen(false)}>
              Why NaijaPay <ArrowRight size={16} />
            </a>
            <a href="#how-it-works" onClick={() => setMenuOpen(false)}>
              How it works <ArrowRight size={16} />
            </a>
          </nav>
        )}
      </header>
      <main id="top">
        {/* Hero */}
        <section className="land-hero">
          <div className="land-hero-inner">
            <div className="land-hero-copy">
              <div className="land-eyebrow">
                <span
                  aria-hidden="true"
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: "#07884f",
                  }}
                />
                YOUR EVERYDAY PAYMENTS, SIMPLIFIED
              </div>
              <h1>
                Your everyday payments,
                <br />
                <span className="land-highlight">made easier.</span>
              </h1>
              <p className="land-description">
                Buy airtime and data, pay electricity bills, renew TV
                subscriptions and purchase supported exam PINs, all from one
                convenient account.
              </p>
              <div className="land-hero-actions">
                <LinkButton to="/register">
                  Create your account <ArrowRight size={18} />
                </LinkButton>
                <LinkButton to="/login" variant="secondary">
                  Log in to NaijaPay
                </LinkButton>
              </div>
              <div className="land-reassurance">
                <span>
                  <CheckCircle2 size={16} />
                  Convenient digital payments
                </span>
                <span>
                  <LockKeyhole size={16} />
                  Account security checks
                </span>
              </div>
            </div>
            <div className="land-hero-art" aria-label="NaijaPay illustration">
              <div className="land-art-glow" />
              <div className="land-art-stage">
                <Hero />
              </div>
              <div className="land-art-badge land-art-badge-top">
                <Zap size={23} />
              </div>
              <div className="land-art-badge land-art-badge-side">
                <Wallet size={22} />
              </div>
              <div className="land-art-caption">
                <div className="land-art-caption-icon">
                  <Check size={21} />
                </div>
                <div>
                  <span>Your payments, in one place</span>
                  <strong>Simple. Convenient. Connected.</strong>
                </div>
                <CheckCircle2
                  className="land-art-check"
                  size={21}
                  aria-hidden="true"
                />
              </div>
            </div>
          </div>
        </section>
        {/* Services */}
        <section
          id="services"
          className="land-section"
          aria-labelledby="land-services-title"
        >
          <div className="land-container">
            <div className="land-section-heading">
              <span className="land-kicker">EVERYDAY ESSENTIALS</span>
              <h2 id="land-services-title">
                More done. Less hassle.
              </h2>
              <p>
                Access supported digital services through a single account
                instead of juggling multiple payment experiences.
              </p>
            </div>
            <div className="land-service-grid">
              {services.map(({ title, description, icon: Icon }) => (
                <article className="land-service-card" key={title}>
                  <div className="land-icon">
                    <Icon size={24} aria-hidden="true" />
                  </div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                  <a
                    href="/register"
                    className="land-inline-link"
                    aria-label={`Get started with NaijaPay for ${title}`}
                  >
                    Get started <ArrowUpRight size={16} />
                  </a>
                </article>
              ))}
            </div>
          </div>
        </section>
        {/* Benefits */}
        <section
          id="benefits"
          className="land-section land-benefits"
          aria-labelledby="land-benefits-title"
        >
          <div className="land-container land-benefits-inner">
            <div className="land-section-copy">
              <span className="land-kicker">WHY NAIJAPAY</span>
              <h2 id="land-benefits-title">
                Payments that put you in control.
              </h2>
              <p>
                Get a more organised way to manage supported purchases, monitor
                transactions and access your account when you need it.
              </p>
              <div className="land-inline-link">
                <LinkButton to="/register">
                  Open your account <ArrowRight size={17} />
                </LinkButton>
              </div>
            </div>
            <div className="land-benefit-grid">
              {benefits.map(({ title, description, icon: Icon }) => (
                <article className="land-benefit-card" key={title}>
                  <div className="land-icon">
                    <Icon size={22} aria-hidden="true" />
                  </div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
        {/* How it works */}
        <section
          id="how-it-works"
          className="land-section"
          aria-labelledby="land-steps-title"
        >
          <div className="land-container">
            <div className="land-section-heading">
              <span className="land-kicker">GETTING STARTED</span>
              <h2 id="land-steps-title">
                Three simple steps.
              </h2>
              <p>
                Start with an account, fund your wallet using an available
                payment method, and choose the service you need.
              </p>
            </div>
            <div className="land-steps">
              {steps.map(({ number, title, description, icon: Icon }) => (
                <article className="land-step" key={number}>
                  <div className="land-step-top">
                    <div className="land-step-number">{number}</div>
                    <div className="land-step-icon">
                      <Icon size={21} aria-hidden="true" />
                    </div>
                  </div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
        {/* Call to action */}
        <section className="land-section">
          <div className="land-container">
            <div className="land-cta">
              <div>
                <span className="land-cta-kicker">
                  GET STARTED WITH NAIJAPAY
                </span>
                <h2>Ready to simplify your payments?</h2>
                <p>
                  Create your account to explore the supported services and
                  payment options available to you.
                </p>
              </div>
              <div className="land-cta-actions">
                <LinkButton to="/register">
                  Create account <ArrowRight size={18} />
                </LinkButton>
                <LinkButton to="/login" variant="secondary">
                  Log in
                </LinkButton>
              </div>
            </div>
          </div>
        </section>
      </main>
      {/* Footer */}
      <footer className="land-footer">
        <div className="land-container land-footer-inner">
          <div className="land-footer-brand">
            <a href="#top" aria-label={`${BRAND.name} homepage`}>
              <Brand />
            </a>
            <p>
              A convenient way to access supported digital payments and
              everyday services.
            </p>
          </div>
          <nav className="land-footer-links" aria-label="Footer navigation">
            <a href="#services">Services</a>
            <a href="#benefits">Why NaijaPay</a>
            <a href="#how-it-works">How it works</a>
            <a href="/login">Log in</a>
            <a href="/register">Register</a>
          </nav>
          <p className="land-copyright">
            ©️ {new Date().getFullYear()} {BRAND.name}
          </p>
        </div>
      </footer>
    </div>
  );
}