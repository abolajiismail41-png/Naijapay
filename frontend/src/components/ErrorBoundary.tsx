import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("ui_error", error, info.componentStack); }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="main stack center" role="alert">
        <h1>Something went wrong</h1>
        <p className="muted">Your money is safe. Reload the page; if a payment was in progress, check Activity before trying again.</p>
        <button className="btn primary" onClick={() => window.location.assign("/home")}>Back to home</button>
      </div>
    );
  }
}
