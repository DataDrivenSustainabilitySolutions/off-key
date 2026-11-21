import type { ReactNode } from "react";
import { Cpu } from "lucide-react";
import type { PipelineProposalSummary, ProposalTest } from "@/types/pipelines.generated";
import { duration, faultsCaught } from "./proposals";

const perDay = (value: number | null | undefined) =>
  value == null ? "–" : value === 0 ? "0" : value < 10 ? value.toFixed(1) : String(Math.round(value));

/** One dot per planted fault, filled where the design alarmed in it. */
export function FaultDots({ test }: { test: ProposalTest }) {
  if (!test.faults?.length) return null;
  return <span className="pl-fault-dots" aria-hidden="true">
    {test.faults.map((fault, index) => <i key={index} className={`is-${fault.outcome}`} />)}
  </span>;
}

/** Sentences as points: a limit reads best one at a time. */
const points = (text: string) => text.split(/(?<=[.;])\s+(?=[A-Z0-9])/).map((item) => item.trim().replace(/[.;]$/, "")).filter(Boolean);

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return <section className="pl-review-section">
    <h3>{title}{aside}</h3>
    {children}
  </section>;
}

/** The readings it binds, behind the device they belong to; one the catalogue lost stands out. */
function ProposalReadings({ proposal }: { proposal: PipelineProposalSummary }) {
  const readings = proposal.readings ?? [];
  const missing = new Set(proposal.missing_readings ?? []);
  const devices = [...new Set(readings.map((reading) => reading.device).filter(Boolean))];
  if (!readings.length) return <p className="pl-review-quiet">It binds no readings.</p>;
  return <ul className="pl-review-chips" aria-label="Readings">
    {devices.map((device) => <li key={`device:${device}`} className="is-device"><Cpu size={13} aria-hidden="true" />{device}</li>)}
    {readings.map((reading) => <li key={reading.id} title={reading.id} className={missing.has(reading.id) ? "is-missing" : undefined}>
      {reading.label}{reading.unit && <small>{reading.unit}</small>}
      {missing.has(reading.id) && <span className="sr-only"> (no longer recorded)</span>}
    </li>)}
  </ul>;
}

/** What the test showed in four figures, then each planted fault and whether it raised an alarm. */
function ProposalEvidence({ proposal }: { proposal: PipelineProposalSummary }) {
  const test = proposal.test;
  const words = proposal.rationale?.evidence;
  if (!proposal.test_run_id)
    return <>{words && <p>{words}</p>}<p className="pl-review-quiet">It was handed in without a test on history.</p></>;
  if (!test)
    return <>{words && <p>{words}</p>}<p className="pl-review-quiet">The test's figures are not worked out yet. Review the design to open the test.</p></>;
  const faults = faultsCaught(test);
  return <>
    <dl className="pl-figures">
      <div><dt>Faults caught</dt><dd>{faults ? <>{faults.caught}<small> / {faults.total}</small></> : "–"}</dd></div>
      <div><dt>False alarms a day</dt><dd>{perDay(test.false_alarms_per_day)}</dd></div>
      <div><dt>History scored</dt><dd>{test.scored_hours}<small> h</small></dd></div>
      <div><dt>Time to alarm</dt><dd>{test.median_delay_seconds == null ? "–" : duration(test.median_delay_seconds)}
        {test.median_delay_seconds != null && <small> median</small>}</dd></div>
    </dl>
    {faults
      ? <>
        <p className="pl-review-quiet">Faults the author planted in real history, and whether the design alarmed:</p>
        <ul className="pl-faults">
          {test.faults!.map((fault, index) => <li key={index} className={`is-${fault.outcome}`}>
            <i aria-hidden="true" />
            <span>{fault.note}</span>
            <small>{fault.outcome === "detected"
              ? `Caught${fault.delay_seconds != null ? ` after ${duration(fault.delay_seconds)}` : ""}`
              : fault.outcome === "missed" ? "Missed" : "Not scored"}</small>
          </li>)}
        </ul>
      </>
      : <p className="pl-review-quiet">The test replayed real history without planted faults, so it counts false alarms only.</p>}
    {words && <p className="pl-review-words"><span>In the author's words</span>{words}</p>}
  </>;
}

/**
 * A proposal as a short report, the same wherever it is read: the readings, the evidence, what it
 * watches and how it decides, its limits as points, and what else the author wrote.
 */
export function ProposalSections({ proposal, compact = false }: { proposal: PipelineProposalSummary; compact?: boolean }) {
  const rationale = proposal.rationale;
  const note = rationale && proposal.reason === rationale.watches ? "" : proposal.reason;
  return <div className={`pl-review-sections${compact ? " is-compact" : ""}`}>
    <Section title="Readings"><ProposalReadings proposal={proposal} /></Section>
    <Section title="Evidence"><ProposalEvidence proposal={proposal} /></Section>
    {rationale && <div className="pl-review-pair">
      <Section title="What it watches"><p>{rationale.watches}</p></Section>
      <Section title="How it decides"><p>{rationale.why}</p></Section>
    </div>}
    {rationale && <Section title="Known limits"><ul className="pl-limits">{points(rationale.limits).map((item) => <li key={item}>{item}</li>)}</ul></Section>}
    {note && <Section title={rationale ? "Author's note" : "Reason"}><p className="pl-brief-note">{note}</p></Section>}
  </div>;
}
