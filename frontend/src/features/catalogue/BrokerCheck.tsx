import { Check, LoaderCircle, Minus, X } from "lucide-react";
import { formatTimeOfDay } from "@/lib/format-time";
import type { SystemConnectionCheck } from "@/types/system";
import { checkTone, type BrokerCheck } from "./useBrokerChecks";

const outcomes: Record<SystemConnectionCheck["status"], string> = {
  reachable: "Reachable",
  auth_rejected: "Login rejected",
  tls_error: "TLS problem",
  unreachable: "Unreachable",
  refused: "Refused",
  timeout: "No response",
  blocked: "Not checkable",
};

/** A small mark beside a broker name; the hover text carries the outcome and reason. */
export function BrokerCheckMark({ check }: { check: BrokerCheck }) {
  if (check.pending) return <LoaderCircle size={14} className="source-check-mark animate-spin" role="img" aria-label="Checking connection" />;
  const status = check.result?.status;
  const outcome = status ? outcomes[status] : "Check failed";
  const label = [outcome, check.result?.message ?? check.error,
    check.result && `Checked at ${formatTimeOfDay(check.result.checked_at)}`].filter(Boolean).join(" · ");
  const Icon = status === "reachable" ? Check : status === "blocked" || !status ? Minus : X;
  const tone = checkTone(check);
  return <Icon size={14} strokeWidth={2.5} className={`source-check-mark source-check-mark--${tone}`} role="img" aria-label={label}>
    <title>{label}</title>
  </Icon>;
}
