import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format-time";
import type { SystemConnectionCheck } from "@/types/system";
import type { BrokerCheck } from "./useBrokerChecks";

const outcomes: Record<SystemConnectionCheck["status"], { label: string; tone: string }> = {
  reachable: { label: "Reachable", tone: "positive" },
  auth_rejected: { label: "Login rejected", tone: "danger" },
  tls_error: { label: "TLS problem", tone: "danger" },
  unreachable: { label: "Unreachable", tone: "danger" },
  refused: { label: "Refused", tone: "danger" },
  timeout: { label: "No response", tone: "warning" },
  blocked: { label: "Not checkable", tone: "neutral" },
};

/** The dot-and-label used for broker states, describing the latest check instead. */
export function BrokerCheckState({ check, detailed = false }: { check: BrokerCheck; detailed?: boolean }) {
  const outcome = check.result && outcomes[check.result.status];
  const label = check.pending ? "Checking…" : outcome ? outcome.label : "Check failed";
  const when = !check.pending && check.result ? formatRelativeTime(check.result.checked_at) : "";
  const latency = detailed && check.result?.latency_ms != null ? `${check.result.latency_ms} ms` : "";
  const reason = check.pending ? undefined : check.result?.message ?? check.error;
  return <span className={`mn-state mn-state--${check.pending ? "neutral" : outcome?.tone ?? "neutral"}`} title={reason ?? undefined}>
    {[label, latency, when && `checked ${when}`].filter(Boolean).join(" · ")}
  </span>;
}

/** Broker detail: re-test one saved broker, e.g. after correcting its settings. */
export function BrokerCheckPanel({ check, onCheck }: { check?: BrokerCheck; onCheck: () => void }) {
  const reason = check && !check.pending ? check.result?.message ?? check.error : undefined;
  return <section className="source-check" aria-label="Connection check">
    <div>
      <Button variant="outline" size="sm" disabled={check?.pending} onClick={onCheck}>Check connection</Button>
      {check ? <BrokerCheckState check={check} detailed /> : <span className="ex-muted">Connects once with the saved settings, then disconnects.</span>}
    </div>
    {reason && <p className="ex-muted">{reason}</p>}
  </section>;
}
