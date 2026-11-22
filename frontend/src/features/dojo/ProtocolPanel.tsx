import type { ProtocolReport } from "@/types/dojo.generated";
import { formatDuration, formatPerDay, formatRate } from "./model";
import { caughtFrom, formatLevel } from "./suites";

/** A study on a protocol suite: the false-alarm budget on the clean copy, then a
 * detection profile per fault family, catches counted where the clean copy was quiet. */
export function ProtocolPanel({ report }: { report: ProtocolReport }) {
  const budget = report.within_budget == null ? "Waiting for the clean copy's run"
    : report.within_budget ? "Within the false-alarm budget" : "Over the false-alarm budget";
  return <section className="dj-protocol" aria-label="Fault-injection protocol">
    <h3 className="dj-section-head">Planted faults · {report.protocol} · {report.purpose}</h3>
    <p className="dj-protocol-headline">{report.headline}</p>
    <dl className="dj-protocol-budget">
      <div><dt>{budget}</dt><dd>{formatPerDay(report.false_alarms_per_day)} false alarms a day and{" "}
        {formatRate(report.alarm_share)} of the time in alarm on the clean copy; the budget is {report.budget_per_day} a
        day and {formatRate(report.budget_share)}.</dd></div>
      <div><dt>Beyond chance</dt><dd>{formatRate(report.adjusted_detection_rate)} of faults, each family weighted
        equally. An alarm that never stops scores 0.</dd></div>
      <div><dt>Simple rules</dt><dd>catch {report.simple_rules_caught} of {report.faults} faults on their own.</dd></div>
      {report.untestable.length > 0 && <div><dt>Did not fit</dt><dd>{report.untestable.length} faults had no room in this
        history.</dd></div>}
    </dl>
    <div className="dj-table-scroll"><table className="dj-table" aria-label="Detection profile">
      <thead><tr><th>Fault</th><th>Caught</th><th>Half caught</th><th>Nine in ten</th><th>Beyond chance</th>
        <th>Simple rules</th><th>Median delay</th><th>By size</th></tr></thead>
      <tbody>{report.families.map(family => <tr key={family.family} className={family.sanity ? "dj-protocol-sanity" : undefined}>
        <td>{family.title}{family.sanity && <small>Every design should catch these</small>}</td>
        <td>{family.caught} of {family.scored}</td>
        <td>{caughtFrom(family)}</td>
        <td>{family.measure === "sigmas" || family.measure === "factor" ? formatLevel(family, family.ninety) : "–"}</td>
        <td>{formatRate(family.adjusted_detection_rate)}</td>
        <td>{family.simple_rules_caught} of {family.faults}</td>
        <td>{formatDuration(family.median_delay_seconds)}
          {family.median_sigmas_at_detection != null && <small>at {formatLevel(family, family.median_sigmas_at_detection)}</small>}</td>
        <td>{family.levels.filter(item => item.level != null).map(item =>
          <span key={item.level} className="dj-protocol-level" title={item.low == null ? undefined
            : `95% interval ${formatRate(item.low)} to ${formatRate(item.high)}`}>
            {formatLevel(family, item.level)} {item.caught}/{item.scored}</span>)}
          {family.levels.some(item => item.confounded) && <small>
            {family.levels.reduce((sum, item) => sum + item.confounded, 0)} set aside: the clean copy alarmed there too</small>}</td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}
