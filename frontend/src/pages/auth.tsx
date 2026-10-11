import { type FormEvent, type ReactNode, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Layout";
import { Banner, Button, TextField } from "../components/ui";
import { api, ApiError, friendly, type TokenPair } from "../lib/api";
import { normalizePhone } from "../lib/phone";

type AuthFrameProps = {
  eyebrow?: string;
  title: string;
  sub?: string;
  children: ReactNode;
  footer?: ReactNode;
};

function AuthFrame({
  eyebrow = "NAIJAPAY ACCOUNT",
  title,
  sub,
  children,
  footer,
}: AuthFrameProps) {
  return (
    <div className="auth-page">
      <header className="auth-header">
        <Link
          to="/"
          className="auth-brand"
          aria-label="NaijaPay home"
        >
          <Brand />
        </Link>

        <div className="auth-header-action">
          <span>Secure payments. Simpler living.</span>
          <span className="auth-status">
            <span className="auth-status-dot" />
            Secure access
          </span>
        </div>
      </header>

      <main className="auth-main">
        <section className="auth-intro">
          <span className="auth-eyebrow">
            <span className="auth-eyebrow-dot" />
            MADE FOR EVERYDAY PAYMENTS
          </span>

          <h1 className="auth-hero-title">
            Your money,
            <br />
            <span>simplified.</span>
          </h1>

          <p className="auth-hero-description">
            One secure place for the payments that keep life moving.
          </p>

          <div className="auth-benefits">
            <div className="auth-benefit">
              <div className="auth-benefit-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
                  <path d="M4 10h16" />
                </svg>
              </div>
              <div>
                <h3>Convenient payments</h3>
                <p>Access everyday payment services in one place.</p>
              </div>
            </div>

            <div className="auth-benefit">
              <div className="auth-benefit-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3 20 6v5c0 5-3.4 8.3-8 10-4.6-1.7-8-5-8-10V6l8-3Z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
              </div>
              <div>
                <h3>Security-conscious access</h3>
                <p>Account protection built into your experience.</p>
              </div>
            </div>

            <div className="auth-benefit">
              <div className="auth-benefit-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3v18M17 7H9.5a3 3 0 0 0 0 6h5a3 3 0 0 1 0 6H6" />
                </svg>
              </div>
              <div>
                <h3>Made for Nigeria</h3>
                <p>Designed for everyday Nigerian transactions.</p>
              </div>
            </div>
          </div>

          <div className="auth-hero-note">
            <span className="auth-hero-note-icon">N</span>
            <div>
              <strong>NaijaPay</strong>
              <span>Your everyday money companion.</span>
            </div>
          </div>

          <div className="auth-orb auth-orb-one" aria-hidden="true" />
          <div className="auth-orb auth-orb-two" aria-hidden="true" />
        </section>

        <section className="auth-panel-wrap">
          <div className="auth-panel">
            <div className="auth-panel-heading">
              <span className="auth-panel-eyebrow">{eyebrow}</span>
              <h2>{title}</h2>
              {sub && <p>{sub}</p>}
            </div>

            {children}

            {footer && <div className="auth-panel-footer">{footer}</div>}
          </div>

          <p className="auth-legal">
            By continuing, use NaijaPay responsibly and keep your account
            credentials private.
          </p>
        </section>
      </main>

      <footer className="auth-bottom">
        <span>©️ {new Date().getFullYear()} NaijaPay</span>
        <span>Payments made simpler.</span>
      </footer>
    </div>
  );
}

export function Register() {
  const nav = useNavigate();
  const { signIn } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const e164 = normalizePhone(phone);

  const errs = {
    name:
      name && name.trim().length < 2
        ? "Enter your full name."
        : null,
    email:
      email &&
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
        ? "Enter a valid email address."
        : null,
    phone:
      phone && !e164
        ? "Enter a valid Nigerian phone number."
        : null,
    password:
      password && password.length < 8
        ? "Use at least 8 characters."
        : null,
  };

  const ok =
    name.trim().length >= 2 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) &&
    !!e164 &&
    password.length >= 8;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!ok || !e164 || busy) return;

    setBusy(true);
    setError(null);

    try {
      const tokens = await api.post<TokenPair>(
        "/api/v1/auth/register",
        {
          full_name: name.trim(),
          email: email.trim().toLowerCase(),
          phone: e164,
          password,
          ...(referralCode.trim()
            ? { referral_code: referralCode.trim().toUpperCase() }
            : {}),
        },
        { auth: false },
      );

      await signIn(tokens);
      nav("/account/pin", {
        replace: true,
        state: { first: true },
      });
    } catch (err) {
      setError(friendly(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="GET STARTED"
      title="Create your account"
      sub="Join NaijaPay and get started with everyday payments."
      footer={
        <p>
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <TextField
          label="Full name"
          value={name}
          onChange={setName}
          autoComplete="name"
          placeholder="Enter your full name"
          error={errs.name ?? undefined}
        />

        <TextField
          label="Email address"
          value={email}
          onChange={setEmail}
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          error={errs.email ?? undefined}
          hint="Used for account communication and wallet-related services."
        />

        <TextField
          label="Phone number"
          value={phone}
          onChange={setPhone}
          inputMode="tel"
          autoComplete="tel"
          placeholder="0803 123 4567"
          error={errs.phone ?? undefined}
        />

        <TextField
          label="Password"
          value={password}
          onChange={setPassword}
          type="password"
          autoComplete="new-password"
          placeholder="At least 8 characters"
          hint="Choose a strong, unique password."
          error={errs.password ?? undefined}
        />

        <TextField
          label="Referral code (optional)"
          value={referralCode}
          onChange={setReferralCode}
          maxLength={16}
          placeholder="Enter referral code"
        />

        {error && <Banner tone="error">{error}</Banner>}

        <Button
          type="submit"
          block
          loading={busy}
          disabled={!ok || busy}
        >
          Create account
        </Button>

        <p className="auth-form-note">
          Your account will be created securely. You can then set up your
          transaction PIN.
        </p>
      </form>
    </AuthFrame>
  );
}

export function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const { signIn } = useAuth();

  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const e164 = normalizePhone(phone);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!e164 || !password || busy) return;

    setBusy(true);
    setError(null);

    try {
      const tokens = await api.post<TokenPair>(
        "/api/v1/auth/login",
        { phone: e164, password },
        { auth: false },
      );

      await signIn(tokens);

      const destination =
        (loc.state as { from?: string } | null)?.from ?? "/home";

      nav(destination, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "phone_not_verified") {
        setError(
          "Your phone number needs verification. Please follow the verification instructions for your account.",
        );
      } else {
        setError(friendly(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="WELCOME BACK"
      title="Sign in to NaijaPay"
      sub="Enter your details to access your account."
      footer={
        <p>
          New to NaijaPay? <Link to="/register">Create an account</Link>
        </p>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <TextField
          label="Phone number"
          value={phone}
          onChange={setPhone}
          inputMode="tel"
          autoComplete="tel"
          placeholder="0803 123 4567"
          error={
            phone && !e164
              ? "Enter a valid Nigerian phone number."
              : undefined
          }
        />

        <TextField
          label="Password"
          value={password}
          onChange={setPassword}
          type="password"
          autoComplete="current-password"
          placeholder="Enter your password"
        />

        <div className="auth-forgot-row">
          <Link to="/reset">Forgot password?</Link>
        </div>

        {error && <Banner tone="error">{error}</Banner>}

        <Button
          type="submit"
          block
          loading={busy}
          disabled={!e164 || !password || busy}
        >
          Sign in
        </Button>

        <div className="auth-security-note">
          <span className="auth-security-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="5" y="10" width="14" height="11" rx="2" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
          </span>
          <span>Your sign-in details are protected. Never share your password.</span>
        </div>
      </form>
    </AuthFrame>
  );
}

export function Verify() {
  const loc = useLocation();
  const nav = useNavigate();
  const { signIn } = useAuth();

  const phone = (loc.state as { phone?: string } | null)?.phone ?? "";

  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (code.length !== 6 || busy) return;

    setBusy(true);
    setError(null);

    try {
      const tokens = await api.post<TokenPair>(
        "/api/v1/auth/verify-phone",
        { phone, code },
        { auth: false },
      );

      await signIn(tokens);
      nav("/account/pin", {
        replace: true,
        state: { first: true },
      });
    } catch (err) {
      setError(friendly(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (!phone) {
    return (
      <AuthFrame
        title="Verify your number"
        sub="Start from registration so we know which number to verify."
      >
        <Banner tone="warn">
          Please return to <Link to="/register">sign up</Link> to continue.
        </Banner>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      eyebrow="PHONE VERIFICATION"
      title="Enter your code"
      sub={`Enter the 6-digit verification code sent to ${phone}.`}
    >
      <form className="auth-form" onSubmit={submit}>
        <label className="auth-field-label" htmlFor="verification-code">
          Verification code
        </label>

        <input
          id="verification-code"
          className="input otp auth-code-input"
          aria-label="6-digit verification code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          autoFocus
          value={code}
          onChange={(e) =>
            setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
          }
        />

        {error && <Banner tone="error">{error}</Banner>}

        <Button
          type="submit"
          block
          loading={busy}
          disabled={code.length !== 6 || busy}
        >
          Verify and continue
        </Button>

        <p className="auth-form-note">
          If you do not receive the code, check your number and try again.
        </p>
      </form>
    </AuthFrame>
  );
}

export function Reset() {
  const nav = useNavigate();

  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const e164 = normalizePhone(phone);

  async function request(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!e164 || busy) return;

    setBusy(true);
    setError(null);

    try {
      await api.post(
        "/api/v1/auth/password/reset/request",
        { phone: e164 },
        { auth: false },
      );

      setStep("code");
    } catch (err) {
      setError(friendly(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!e164 || code.length !== 6 || password.length < 8 || busy) {
      return;
    }

    setBusy(true);
    setError(null);

    try {
      await api.post(
        "/api/v1/auth/password/reset/confirm",
        {
          phone: e164,
          code,
          new_password: password,
        },
        { auth: false },
      );

      setDone(true);
    } catch (err) {
      setError(friendly(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <AuthFrame
        eyebrow="ALL DONE"
        title="Password updated"
        sub="Your password has been changed successfully."
        footer={
          <p>
            Ready to continue? <Link to="/login">Sign in</Link>
          </p>
        }
      >
        <Banner>Your new password is ready to use.</Banner>
        <Button block onClick={() => nav("/login", { replace: true })}>
          Return to sign in
        </Button>
      </AuthFrame>
    );
  }

  if (step === "phone") {
    return (
      <AuthFrame
        eyebrow="ACCOUNT RECOVERY"
        title="Reset your password"
        sub="Enter your Nigerian phone number to request a reset code."
        footer={
          <p>
            Remembered your password? <Link to="/login">Sign in</Link>
          </p>
        }
      >
        <form className="auth-form" onSubmit={request} noValidate>
          <TextField
            label="Phone number"
            value={phone}
            onChange={setPhone}
            inputMode="tel"
            autoComplete="tel"
            placeholder="0803 123 4567"
            error={
              phone && !e164
                ? "Enter a valid Nigerian phone number."
                : undefined
            }
          />

          {error && <Banner tone="error">{error}</Banner>}

          <Button type="submit" block loading={busy} disabled={!e164 || busy}>
            Request reset code
          </Button>
        </form>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      eyebrow="ACCOUNT RECOVERY"
      title="Choose a new password"
      sub="Enter your reset code and create a new password."
      footer={
        <p>
          Need to start again? <button type="button" className="auth-text-button" onClick={() => { setStep("phone"); setCode(""); setError(null); }}>Change phone number</button>
        </p>
      }
    >
      <form className="auth-form" onSubmit={confirm}>
        <label className="auth-field-label" htmlFor="reset-code">
          Reset code
        </label>

        <input
          id="reset-code"
          className="input otp auth-code-input"
          aria-label="6-digit reset code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(e) =>
            setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
          }
        />

        <TextField
          label="New password"
          value={password}
          onChange={setPassword}
          type="password"
          autoComplete="new-password"
          placeholder="At least 8 characters"
          hint="Choose a strong, unique password."
        />

        {error && <Banner tone="error">{error}</Banner>}

        <Button
          type="submit"
          block
          loading={busy}
          disabled={code.length !== 6 || password.length < 8 || busy}
        >
          Update password
        </Button>
      </form>
    </AuthFrame>
  );
}