import { Check, CircleAlert, LoaderCircle, Minus } from "lucide-react";
import { formatTimeOfDay } from "@/lib/format-time";
import { checkTone, outcomes, type BrokerCheck } from "./useBrokerChecks";

/** The outcome and time of a finished check, with its reason when the problem does not already say it. */
function checkSummary(check: BrokerCheck, problem?: string) {
  const status = check.result?.status;
  const reason = check.result?.message ?? check.error;
  return [status ? outcomes[status] : "Check failed", reason !== problem ? reason : undefined,
    check.result && `Checked at ${formatTimeOfDay(check.result.checked_at)}`].filter(Boolean).join(" · ");
}

/** A small mark beside a broker name: "!" for a problem, otherwise the outcome of its last check. */
export function BrokerCheckMark({ check, problem, tone = "danger" }: { check?: BrokerCheck; problem?: string;
  tone?: "warning" | "danger" }) {
  if (check?.pending) return <LoaderCircle size={14} className="source-check-mark animate-spin" role="img" aria-label="Checking connection" />;
  if (!problem && !check) return null;
  const status = check?.result?.status;
  const label = [problem, check && checkSummary(check, problem)].filter(Boolean).join(" · ");
  const Icon = problem ? CircleAlert : status === "reachable" ? Check : Minus;
  return <Icon size={14} strokeWidth={2.5} role="img" aria-label={label}
    className={`source-check-mark source-check-mark--${problem ? tone : checkTone(check)}`}><title>{label}</title></Icon>;
}
