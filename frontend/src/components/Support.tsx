import { useLocation, useParams } from "react-router-dom";
import { BRAND } from "../config";

type SupportProps = {
  transaction?: {
    reference: string;
    status?: string;
    service?: string;
    amount?: string;
  };
  compact?: boolean;
};

const WHATSAPP_NUMBER =
  import.meta.env.VITE_SUPPORT_WHATSAPP_NUMBER || "2347041342767";

const SUPPORT_EMAIL =
  import.meta.env.VITE_SUPPORT_EMAIL?.trim() || "";

export default function Support({
  transaction,
  compact = false,
}: SupportProps) {
  const location = useLocation();
  const { ref } = useParams();

  const reference = transaction?.reference || ref;

  const message = [
    `Hello ${BRAND.name} Support, I need assistance.`,
    reference ? `Transaction reference: ${reference}` : "",
    transaction?.service ? `Service: ${transaction.service}` : "",
    transaction?.status ? `Status: ${transaction.status}` : "",
    transaction?.amount ? `Amount: ${transaction.amount}` : "",
    !reference ? `Page: ${location.pathname}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  const whatsappUrl = `https://wa.me/${WHATSAPP_NUMBER.replace(
    /\D/g,
    "",
  )}?text=${encodeURIComponent(message)}`;

  const emailSubject = reference
    ? `NaijaPay Support - Transaction ${reference}`
    : "NaijaPay Customer Support";

  const emailUrl = SUPPORT_EMAIL
    ? `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
        emailSubject,
      )}&body=${encodeURIComponent(message)}`
    : undefined;

  return (
    <section
      className={`support-panel${compact ? " support-panel-compact" : ""}`}
      aria-labelledby="support-heading"
    >
      <div className="support-copy">
        <h2 id="support-heading">
          {reference ? "Need help with this transaction?" : "Need help?"}
        </h2>
        <p>
          Contact our support team if you have questions about payments,
          failed transactions, or your NaijaPay account.
        </p>
      </div>

      <div className="support-actions">
        <a
          className="support-button support-whatsapp"
          href={whatsappUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span aria-hidden="true">◉</span>
          Chat on WhatsApp
        </a>

        {emailUrl ? (
          <a className="support-button support-email" href={emailUrl}>
            <span aria-hidden="true">✉</span>
            Email support
          </a>
        ) : (
          <button
            className="support-button support-email"
            type="button"
            disabled
            title="Email support has not been configured yet."
          >
            <span aria-hidden="true">✉</span>
            Email support coming soon
          </button>
        )}
      </div>
    </section>
  );
}