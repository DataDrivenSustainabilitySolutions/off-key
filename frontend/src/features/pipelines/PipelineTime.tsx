import { useId } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { TIME_FEATURES, timeFeatures } from "./scope";

type Issue = { path: (string | number)[]; message: string };

/** What each feature holds, said once below the list for the ones that are chosen. */
const MEANINGS: Record<string, string> = {
  elapsed: "dt is in seconds and needs an observation before it, so the step is ready after two.",
  hour: "hour runs from 0 at midnight up to 24, with minutes as a fraction.",
  weekday: "weekday is 1 on Monday and 7 on Sunday.",
  daily_cycle: "hour_sin and hour_cos place the time of day on a circle, where 23:59 lies next to 0:00.",
  weekly_cycle: "weekday_sin and weekday_cos place the time of week on a circle, where Sunday night lies next to Monday morning.",
};

/** The zones this browser knows, offered while typing; the check accepts any zone RADAR knows. */
const ZONES: string[] = (() => {
  const supported = (Intl as { supportedValuesOf?: (key: "timeZone") => string[] }).supportedValuesOf;
  return supported ? ["UTC", ...supported("timeZone").filter((zone) => zone !== "UTC")] : [];
})();

/** The features a Time features step adds, and the time zone its hour and weekday follow. */
export function PipelineTime({ node, component, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  issues: Issue[];
  readOnly?: boolean;
  onChange: (params: Record<string, JsonValue>, field: string) => void;
}) {
  const id = useId();
  const chosen = timeFeatures(node, component).map(([name]) => name);
  // Only the hour and the weekday follow a clock; dt is the same in every zone.
  const calendar = chosen.some((name) => name !== "elapsed");
  const field = (name: string) => component.fields.find((item) => item.name === name);
  /** Set one setting, leaving it out where it holds the step's default. */
  const set = (name: string, value: JsonValue | undefined) => {
    const params = { ...node.params };
    if (value === undefined || value === field(name)?.default) delete params[name];
    else params[name] = value;
    onChange(params, name);
  };
  const errors = issues.filter((issue) => TIME_FEATURES.some(([name]) => name === issue.path[0]));
  const zoneErrors = issues.filter((issue) => issue.path[0] === "timezone");
  return <div className="pl-scope">
    <fieldset className="pl-field" aria-describedby={`${id}-adds ${id}-adds-errors`}>
      <legend>Adds</legend>
      <div className="pl-scope-features">
        {TIME_FEATURES.map(([name, names]) => {
          const checked = chosen.includes(name);
          return <label className="parameter-check" key={name}>
            {/* The step adds something, so the last choice stays. */}
            <input type="checkbox" checked={checked} disabled={readOnly || (checked && chosen.length === 1)}
              onChange={(event) => set(name, event.target.checked)} />
            {field(name)?.label ?? name} <small>{names.join(", ")}</small>
          </label>;
        })}
      </div>
      <small className="pl-help" id={`${id}-adds`}>
        {chosen.map((name) => MEANINGS[name]).join(" ")}
      </small>
      <div id={`${id}-adds-errors`}>
        {errors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
      </div>
    </fieldset>
    {calendar && <div className="pl-field">
      <label htmlFor={`${id}-zone`}>Time zone</label>
      <input id={`${id}-zone`} value={typeof node.params.timezone === "string" ? node.params.timezone : ""}
        placeholder="UTC" maxLength={64} spellCheck={false} disabled={readOnly} list={`${id}-zones`}
        aria-invalid={zoneErrors.length > 0} aria-describedby={`${id}-zone-help ${id}-zone-errors`}
        onChange={(event) => set("timezone", event.target.value.trim() || undefined)} />
      <datalist id={`${id}-zones`}>
        {ZONES.map((zone) => <option key={zone} value={zone} />)}
      </datalist>
      <small className="pl-help" id={`${id}-zone-help`}>
        The clock the hour and the weekday follow, with its daylight saving time, such as Europe/Berlin.
        Leave empty for UTC.
      </small>
      <div id={`${id}-zone-errors`}>
        {zoneErrors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
      </div>
    </div>}
  </div>;
}
