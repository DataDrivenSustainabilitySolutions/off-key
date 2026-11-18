import { Bot, User } from "lucide-react";
import { RelativeTime } from "@/components/RelativeTime";
import { stepLabels } from "@/domain/monitoring/monitorOrigin";
import type { MonitorRationale, MonitorRecord } from "@/types/pipelines.generated";
import "./rationale.css";

/** The four parts of a rationale, in the order a member reads them. */
const RATIONALE_FIELDS: { key: keyof MonitorRationale; label: string }[] = [
  { key: "watches", label: "Watches" },
  { key: "why", label: "Why this design" },
  { key: "evidence", label: "Evidence" },
  { key: "limits", label: "Limits" },
];

/** Who designed it: an agent by its key's name, a member by name. */
export function AuthorChip({ author, kind }: { author: string; kind: "agent" | "member" }) {
  return <span className="rationale-author" title={kind === "agent" ? `Designed by the agent ${author}` : `Designed by ${author}`}>
    {kind === "agent" ? <Bot size={13} aria-hidden="true" /> : <User size={13} aria-hidden="true" />}
    {kind === "agent" ? `Agent · ${author}` : author}
  </span>;
}

/**
 * The fields as labelled rows. `only` names the ones a summary shows, in the order a member reads them;
 * `stacked` puts each label above its text, where the column is too narrow for both side by side.
 */
export function RationaleFields({ rationale, only, stacked = false }: {
  rationale: MonitorRationale;
  only?: (keyof MonitorRationale)[];
  stacked?: boolean;
}) {
  return <dl className={`rationale-fields${stacked ? " rationale-fields--stacked" : ""}`}>
    {RATIONALE_FIELDS.filter(({ key }) => !only || only.includes(key)).map(({ key, label }) =>
      <div key={key}><dt>{label}</dt><dd>{rationale[key]}</dd></div>)}
  </dl>;
}

/**
 * What a monitor watches and why, under the source header: one line that names who designed it,
 * and on opening the four fields and each start and stop. Closed by default, so the chart stays first.
 */
export function RationaleCard({ author, authorKind, rationale, history = [], open = false }: {
  author: string;
  authorKind: "agent" | "member";
  rationale?: MonitorRationale | null;
  history?: MonitorRecord[];
  open?: boolean;
}) {
  const labels = stepLabels(history);
  const steps = history.map((record, index) => ({ record, label: labels[index]! })).reverse();
  return <details className="rationale-card" open={open || undefined}>
    <summary>
      <span className="rationale-watches">
        {rationale ? <><span className="rationale-label">Watches</span> {rationale.watches}</> : <span className="rationale-label">No rationale recorded</span>}
      </span>
      <AuthorChip author={author} kind={authorKind} />
    </summary>
    <div className="rationale-body">
      {rationale && <RationaleFields rationale={rationale} />}
      {history.length > 0 && <ol className="rationale-history" aria-label="Starts and stops">
        {steps.map(({ record, label }, index) => <li key={`${record.at}-${index}`}>
          <span><strong>{label}</strong> by {record.author_kind === "agent" ? `the agent ${record.author}` : record.author}{" "}
            <RelativeTime value={record.at} />{record.test_run_id ? " · after a test" : ""}</span>
          {record.note && <small>{record.note}</small>}
        </li>)}
      </ol>}
    </div>
  </details>;
}
