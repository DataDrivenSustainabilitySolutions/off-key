import { useId, useState } from "react";
import {
  alarmBudget, BUDGET_PERIODS, budgetCount, budgetNumber, budgetPeriod, budgetSentence, budgetShare, scoresPerAlarm,
  withAlarmShare, type BudgetPeriod,
} from "./alarmBudget";
import type { PipelineComponent } from "./contracts";
import type { GraphDocument } from "./model";
import type { HistoryMode } from "./types";

/** How often the design may alarm, as a count in a period. The design keeps it as the alarm
 * rate of its calibration step, or as the quantile of its threshold, so the steps and this
 * setting always agree. Without a measured interval it reads as one score in so many. */
export function AlarmBudgetSetting({
  document, components, interval, gated, shortfall, readOnly, onChange,
}: {
  document: GraphDocument;
  components: PipelineComponent[];
  /** Seconds between observations, when every reading has a measured interval. */
  interval?: number;
  gated?: boolean;
  /** What the check says when the calibration window is too short for this budget. */
  shortfall?: string;
  readOnly: boolean;
  onChange: (document: GraphDocument, history?: HistoryMode) => void;
}) {
  const field = useId();
  const help = useId();
  const errorId = useId();
  const [chosen, setChosen] = useState<BudgetPeriod["id"]>();
  // What was typed stays as typed while it is the design's budget; any other budget shows rounded.
  const [typed, setTyped] = useState<{ text: string; editing: boolean }>();
  const budget = alarmBudget(document.definition, components);
  if (!budget) return null;
  const period = interval
    ? BUDGET_PERIODS.find((item) => item.id === chosen) ?? budgetPeriod(budget.share, interval)
    : undefined;
  const shareOf = (text: string) => {
    const value = text.trim() === "" ? NaN : Number(text);
    return interval && period ? budgetShare(value, interval, period) : Number.isInteger(value) ? 1 / value : NaN;
  };
  const kept = typed && (typed.editing || Math.abs(shareOf(typed.text) - budget.share) <= budget.share * 1e-4);
  const shown = kept ? typed.text : String(interval && period
    ? budgetNumber(budgetCount(budget.share, interval, period)) : scoresPerAlarm(budget.share));
  const share = shareOf(shown);
  const error = share > 0 && share < 1 ? ""
    : shown.trim() === "" || Number.isNaN(Number(shown)) ? "Enter a number."
      : interval && period
        ? Number(shown) <= 0 ? "Use a number above 0."
          : `Use fewer than ${budgetNumber(period.seconds / interval).toLocaleString()}, which is every score.`
        : Number.isInteger(Number(shown)) ? "Use at least 2." : "Enter a whole number.";
  return (
    <>
      <div className="pl-field pl-budget">
        <label htmlFor={field}>Alarm budget</label>
        <div className="pl-budget-value">
          {!period && <span>1 in</span>}
          <input
            id={field}
            type="number"
            inputMode="decimal"
            step="any"
            min={period ? 0 : 2}
            value={shown}
            disabled={readOnly}
            aria-invalid={!!error}
            aria-describedby={error ? `${errorId} ${help}` : help}
            onChange={(event) => {
              const text = event.target.value;
              setTyped({ text, editing: true });
              // The period stays while a number is typed, or the number would change its meaning.
              if (period) setChosen(period.id);
              const next = shareOf(text);
              if (next > 0 && next < 1) onChange(withAlarmShare(document, budget, next), "setting:budget");
            }}
            onBlur={() => setTyped((previous) => previous && { ...previous, editing: false })}
          />
          {period
            ? <select aria-label="Budget period" value={period.id}
                onChange={(event) => { setChosen(event.target.value as BudgetPeriod["id"]); setTyped(undefined); }}>
                {BUDGET_PERIODS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            : <span>scores</span>}
        </div>
        {error && <small className="pl-field-error" id={errorId}>{error} The last valid value is kept.</small>}
      </div>
      <p className="pl-help" id={help}>{budgetSentence(budget, { interval, gated, short: !!shortfall })}</p>
      {shortfall && <p className="pl-warning" role="status">{shortfall}</p>}
    </>
  );
}
