import { useId, useState } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { duration } from "./lagContext";
import { PipelineLagContext } from "./PipelineLagContext";
import { LAG_UNITS, lagText, lagUnit, lagsOf, parseLags, setting } from "./scope";

type Issue = { path: (string | number)[]; message: string };

/** Common choices, one press each, for lags in observations and in time. */
const PRESETS: Record<"counted" | "timed", { label: string; lags: number[] }[]> = {
  counted: [
    { label: "1-3", lags: [1, 2, 3] },
    { label: "1-6", lags: [1, 2, 3, 4, 5, 6] },
    { label: "1-12", lags: Array.from({ length: 12 }, (_item, index) => index + 1) },
    { label: "1, 2, 4, 8, 16", lags: [1, 2, 4, 8, 16] },
  ],
  timed: [
    { label: "1, 5, 15", lags: [1, 5, 15] },
    { label: "1, 6, 24", lags: [1, 6, 24] },
    { label: "1-3", lags: [1, 2, 3] },
    { label: "1, 7", lags: [1, 7] },
  ],
};

const same = (one: number[], other: number[]) => one.length === other.length && one.every((item, index) => item === other[index]);

/** A Lags step's unit and lags, typed as people write them: 1-3, 24. */
export function PipelineLags({ node, component, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  issues: Issue[];
  readOnly?: boolean;
  onChange: (params: Record<string, JsonValue>, field: string) => void;
}) {
  const id = useId();
  const lags = lagsOf(node, component);
  const unit = lagUnit(node, component);
  const unitName = String(setting(node, component, "unit") ?? "minutes");
  // What is being typed; a change from elsewhere, such as a preset or an undo, shows instead.
  const [draft, setDraft] = useState<string | null>(null);
  const typed = draft === null ? undefined : parseLags(draft);
  const text = draft !== null && (!typed || !("lags" in typed) || same(typed.lags, lags)) ? draft : lagText(lags);
  const parsed = parseLags(text);
  const field = (name: string) => component.fields.find((item) => item.name === name);
  const set = (name: string, value: JsonValue) => {
    const params = { ...node.params };
    if (JSON.stringify(value) === JSON.stringify(field(name)?.default)) delete params[name];
    else params[name] = value;
    onChange(params, name);
  };
  const type = (value: string) => {
    setDraft(value);
    const result = parseLags(value);
    if ("lags" in result && !same(result.lags, lags)) set("lags", result.lags);
  };
  const errors = issues.filter((issue) => issue.path[0] === "lags" || issue.path[0] === "unit");
  const largest = lags[lags.length - 1];
  const presets = PRESETS[unit.seconds ? "timed" : "counted"];
  return <div className="pl-field pl-lags">
    <label htmlFor={`${id}-unit`}>Count lags in</label>
    <select id={`${id}-unit`} value={unitName} disabled={readOnly} onChange={(event) => set("unit", event.target.value)}>
      {Object.entries(LAG_UNITS).map(([name, item]) => <option key={name} value={name}>{item.label}</option>)}
    </select>
    <label htmlFor={`${id}-lags`}>Lags</label>
    <input id={`${id}-lags`} value={text} disabled={readOnly} inputMode="numeric" spellCheck={false}
      placeholder="1-3, 24" aria-invalid={"error" in parsed || errors.length > 0}
      aria-describedby={`${id}-lags-help ${id}-lags-errors`}
      onChange={(event) => type(event.target.value)}
      onBlur={() => setDraft(null)} />
    <div className="pl-segmented" role="group" aria-label="Common lags">
      {presets.map((preset) => <button key={preset.label} type="button" disabled={readOnly}
        aria-pressed={same(preset.lags, lags)} onClick={() => { setDraft(null); set("lags", preset.lags); }}>
        {preset.label}
      </button>)}
    </div>
    <small className="pl-help" id={`${id}-lags-help`}>
      {unit.seconds
        ? <>How far back, as numbers or ranges such as 1-3, 24. Each lag is the last value at or before that
          long ago, found within 1% of the lag{largest ? `, such as ${largest} ${unit.short} within ${duration(largest * unit.seconds / 100)}` : ""}.
          {largest ? ` The step has output once ${largest} ${unit.short} have passed.` : ""}</>
        : <>Observations back, as numbers or ranges such as 1-3, 24.
          {largest ? ` The step has output from the ${ordinal(largest + 1)} observation on.` : ""}
          {" "}Only a steady interval makes a lag a fixed time back; count in time otherwise.</>}
    </small>
    <div id={`${id}-lags-errors`}>
      {"error" in parsed && <p className="pl-field-error" role="alert">{parsed.error}</p>}
      {errors.map((issue, index) => <p key={index} className="pl-field-error" role="alert">{issue.message}</p>)}
    </div>
    <PipelineLagContext lags={lags} unit={unit} readOnly={readOnly} onLags={(next) => { setDraft(null); set("lags", next); }} />
  </div>;
}

function ordinal(value: number) {
  const tens = value % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th";
  return `${value}${suffix}`;
}
