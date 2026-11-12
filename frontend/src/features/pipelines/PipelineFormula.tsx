import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { calculateLine, CONSTANTS, inCondition, suggestions, typedWord, writtenNames, type Suggestion } from "./formula";
import { addedName, addsByDefault, combinedName, EACH_VARIABLE, eachSuffix, formulaEach, formulaName, listed } from "./scope";

type Fix = { start: number; end: number; text: string };
type Issue = { path: (string | number)[]; message: string; fix?: Fix | null };
type Change = (params: Record<string, JsonValue>, field: string) => void;

const errorsOf = (issues: Issue[], field: string) => issues.filter((issue) => issue.path[0] === field);

function Errors({ id, issues, onFix }: { id: string; issues: Issue[]; onFix?: (fix: Fix) => void }) {
  return <div id={id}>
    {issues.map((issue, index) => <p key={index} className="pl-field-error" role="alert">
      {issue.message}
      {issue.fix && onFix && <>{" "}<button type="button" className="pl-formula-fix" onClick={() => onFix(issue.fix!)}>
        Use {issue.fix.text}
      </button></>}
    </p>)}
  </div>;
}

/** Set one setting, or leave it out so the step uses its default. */
function setter(node: PipelineNode, onChange: Change) {
  return (field: string, value: JsonValue | undefined) => {
    const params = { ...node.params };
    if (value === undefined) delete params[field];
    else params[field] = value;
    onChange(params, field);
  };
}

/** The name of the feature an Aggregate or Formula computes, or the one a Set feature writes. */
export function CombinedName({ node, component, features, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  /** The features that arrive; Set feature offers them, since it may replace one. */
  features?: string[];
  issues: Issue[];
  readOnly?: boolean;
  onChange: Change;
}) {
  const id = useId();
  const errors = errorsOf(issues, "name");
  const set = setter(node, onChange);
  const fallback = combinedName({ ...node, params: { ...node.params, name: null } }, component);
  const replaceable = node.component === "prepare.set" && features?.length ? features : undefined;
  return <div className="pl-field">
    <label htmlFor={`${id}-name`}>Name</label>
    <input id={`${id}-name`} value={typeof node.params.name === "string" ? node.params.name : ""}
      placeholder={fallback} maxLength={120} spellCheck={false} disabled={readOnly}
      // Some browsers hide a list of suggestions from a field with autocomplete off.
      autoComplete={replaceable ? undefined : "off"} list={replaceable && `${id}-name-features`}
      aria-invalid={errors.length > 0} aria-describedby={`${id}-name-help ${id}-name-errors`}
      onChange={(event) => set("name", event.target.value || undefined)} />
    {replaceable && <datalist id={`${id}-name-features`}>
      {replaceable.map((feature) => <option key={feature} value={feature} />)}
    </datalist>}
    <small className="pl-help" id={`${id}-name-help`}>
      {node.component === "prepare.set"
        ? `The feature to add or replace. Other features stay unchanged. Leave empty for ${fallback}.`
        : `The computed feature, in letters, digits and underscores. Leave empty for ${fallback}.`}
    </small>
    <Errors id={`${id}-name-errors`} issues={errors} />
  </div>;
}

type Text = {
  /** The setting that holds the text. */
  field: string;
  condition?: boolean;
  label?: string;
  placeholder?: string;
  /** Left out when empty, for a condition a step can do without. */
  optional?: boolean;
  /** One name = formula per line, each reading the lines above it. */
  lines?: boolean;
};

/** Where a step keeps what is written in this editor; a step not listed writes a formula. */
const TEXTS: Record<string, Text> = {
  "prepare.gate": { field: "condition", condition: true },
  "prepare.mute": { field: "condition", condition: true, label: "Mute while", placeholder: "speed < 100" },
  "prepare.condition": { field: "condition", condition: true },
  "prepare.accumulate": { field: "reset_when", condition: true, label: "Reset when", placeholder: "dc_current < 1", optional: true },
  "prepare.hold": { field: "update_when", condition: true, label: "Update when" },
  "prepare.calculate": { field: "formulas", label: "Formulas", placeholder: "power = dc_voltage * dc_current", lines: true },
};
const FORMULA: Text = { field: "expression" };

/** A Formula's expression, a condition or the lines of a Calculate step, written over the
 * features that arrive. */
export function PipelineFormula({ node, component, features, featureLabels, readings, featureHint, issues, readOnly, range, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  /** Incoming feature names in their order, once the graph has been checked. */
  features: string[];
  featureLabels: Record<string, string>;
  /** The incoming features that follow one reading; For each starts with them. */
  readings?: string[];
  /** Shown in place of the features while they are unknown: why, and where to fix it. */
  featureHint?: ReactNode;
  issues: Issue[];
  readOnly?: boolean;
  /** The values the computed feature can take, as the check inferred them. */
  range?: string;
  onChange: Change;
}) {
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const spec = TEXTS[node.component] ?? FORMULA;
  const condition = !!spec.condition;
  const formula = node.component === "prepare.formula";
  // Only a step that computes one named feature has a Result, a Name and a range to show.
  const named = ["prepare.formula", "prepare.condition", "prepare.set"].includes(node.component);
  const field = spec.field;
  const text = typeof node.params[field] === "string" ? node.params[field] : "";
  const errors = errorsOf(issues, field);
  const set = setter(node, onChange);
  const help = component.fields.find((item) => item.name === field)?.description;
  // A Formula for each feature runs once per chosen feature, with x standing for it.
  const each = formula ? formulaEach(node) : undefined;
  // A line of a Calculate step reads the features the lines above it write as well.
  const extra = (written: string[]) => written.filter((name) => !features.includes(name));
  const names = each ? [EACH_VARIABLE, ...features] : spec.lines ? [...features, ...extra(writtenNames(text))] : features;
  const labels = each ? { ...featureLabels, [EACH_VARIABLE]: "each chosen feature" } : featureLabels;
  // The caret while the field has focus and nothing is selected; suggestions follow it.
  const [caret, setCaret] = useState<number>();
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState<string>();
  const word = caret === undefined || readOnly ? undefined : typedWord(text, caret);
  const key = word && `${word.start}:${word.prefix}`;
  const line = word && spec.lines ? calculateLine(text, word.start) : undefined;
  const options = !word || key === dismissed ? []
    : line
      // The name before the equals sign is a feature to replace or a new one.
      ? suggestions(word, [...features, ...extra(line.above)], labels,
        inCondition(text.slice(line.start), word.start - line.start, false))
        .filter((item) => !line.naming || item.kind === "feature")
      : suggestions(word, names, labels, inCondition(text, word.start, condition));
  const open = options.length > 0;
  const current = Math.min(active, Math.max(options.length - 1, 0));
  // The chosen suggestion stays in view, in the list and in a panel that scrolls.
  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>(".is-active")?.scrollIntoView?.({ block: "nearest" });
  }, [open, current]);
  const track = () => {
    const element = area.current;
    if (!element) return;
    setCaret(element.selectionStart === element.selectionEnd ? element.selectionStart : undefined);
  };
  // Text goes in place of a range, and the caret lands where the text ends, or at offset into it.
  const write = (start: number, end: number, token: string, offset = token.length) => {
    set(field, text.slice(0, start) + token + text.slice(end));
    setActive(0);
    setCaret(start + offset);
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(start + offset, start + offset);
    });
  };
  // A name goes in where the cursor is, replacing any selection.
  const insert = (name: string) => {
    const element = area.current;
    write(element?.selectionStart ?? text.length, element?.selectionEnd ?? text.length, formulaName(name));
  };
  const accept = (item: Suggestion) => {
    if (!word) return;
    if (item.kind === "feature") return write(word.start, word.end, formulaName(item.value));
    if (item.kind === "keyword") return write(word.start, word.end, `${item.value} `);
    // A function opens its parentheses, and the caret goes between them, or behind
    // them where the function takes no value.
    const called = text[word.end] === "(";
    write(word.start, word.end, called ? item.value : `${item.value}()`,
      item.value.length + (CONSTANTS.has(item.value) && !called ? 2 : 1));
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!open) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      setActive((current + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
    } else if (event.key === "Enter" || event.key === "Tab") {
      accept(options[current]!);
    } else if (event.key === "Escape") {
      // Closes the list only; the settings panel stays open.
      setDismissed(key);
      event.stopPropagation();
    } else return;
    event.preventDefault();
  };
  const add = (node.params.result ?? (addsByDefault(component) ? "add" : "replace")) === "add";
  const name = combinedName(node, component);
  const listId = `${id}-suggestions`;
  const suffix = eachSuffix(node);
  // Choosing For each starts with the readings that arrive, the usual case: x / mean - 1 per phase.
  const setMode = (forEach: boolean) => {
    const params = { ...node.params };
    if (forEach) {
      const start = (readings ?? features.filter((feature) => feature in featureLabels))
        .filter((feature) => features.includes(feature));
      params.apply_to = start.length ? start : features;
      delete params.name;
    } else {
      delete params.apply_to;
      delete params.suffix;
    }
    onChange(params, "apply_to");
  };
  // Names that no longer arrive stay listed until they are unchecked.
  const missing = each?.filter((feature) => !features.includes(feature)) ?? [];
  const toggle = (feature: string, checked: boolean) => set("apply_to", [
    ...features.filter((item) => item === feature ? checked : each?.includes(item)),
    ...missing.filter((item) => item !== feature),
  ]);
  const outcome = each
    ? add
      ? each.length ? `Keeps the features and adds ${listed(each.map((item) => addedName(item, suffix)))}.` : "Keeps the features and adds one per chosen feature."
      : `Replaces ${each.length ? listed(each) : "the chosen features"} with their results.`
    : add ? `Keeps the features and adds ${name}.` : `Replaces the features the formula reads with ${name}.`;
  return <div className="pl-formula">
    {formula && <div className="pl-field">
      <span id={`${id}-mode`}>Computes</span>
      <div className="pl-segmented" role="group" aria-labelledby={`${id}-mode`}>
        <button type="button" disabled={readOnly} aria-pressed={!each} onClick={() => each && setMode(false)}>One feature</button>
        <button type="button" disabled={readOnly} aria-pressed={!!each} onClick={() => !each && setMode(true)}>For each feature</button>
      </div>
      <small className="pl-help">
        {each ? "Runs the formula once for each chosen feature, with x standing for it."
          : "Computes one feature from the features that arrive."}
      </small>
    </div>}
    {each && <fieldset className="pl-field" aria-describedby={`${id}-each ${id}-each-errors`}>
      <legend>For each</legend>
      <small className="pl-help" id={`${id}-each`}>
        {each.length ? `x stands for ${listed(each)}, one after another.` : "Choose the features x stands for."}
      </small>
      {!features.length && !missing.length
        ? featureHint ?? <p className="pl-help">Connect an input to choose features.</p>
        : <div className="pl-scope-features">
          {features.map((feature) => <label className="parameter-check" key={feature}>
            <input type="checkbox" checked={each.includes(feature)} disabled={readOnly}
              onChange={(event) => toggle(feature, event.target.checked)} />
            {featureLabels[feature] ?? feature}
          </label>)}
          {missing.map((feature) => <label className="parameter-check is-missing" key={feature}>
            <input type="checkbox" checked disabled={readOnly} onChange={() => toggle(feature, false)} />
            {feature} <small>not available here</small>
          </label>)}
        </div>}
      <Errors id={`${id}-each-errors`} issues={errorsOf(issues, "apply_to")} />
    </fieldset>}
    <div className="pl-field">
      <label htmlFor={`${id}-text`}>{spec.label ?? (condition ? "Condition" : "Formula")}</label>
      <div className="pl-formula-input">
        <textarea ref={area} id={`${id}-text`} className="pl-code" rows={spec.lines ? 6 : 3}
          maxLength={spec.lines ? 4096 : 512} value={text}
          placeholder={spec.placeholder ?? (condition ? "dc_current > 1" : each ? "x / mean - 1" : "dc_voltage * dc_current")} disabled={readOnly}
          spellCheck={false} autoComplete="off" autoCapitalize="off" autoCorrect="off"
          aria-invalid={errors.length > 0} aria-describedby={`${id}-errors ${id}-help`}
          aria-autocomplete="list" aria-controls={open ? listId : undefined}
          aria-activedescendant={open ? `${listId}-${current}` : undefined}
          onChange={(event) => {
            set(field, spec.optional ? event.target.value || undefined : event.target.value);
            setActive(0);
            setCaret(event.target.selectionStart === event.target.selectionEnd ? event.target.selectionStart : undefined);
          }}
          onSelect={track} onClick={track} onKeyDown={keyDown}
          onBlur={() => setCaret(undefined)} />
        {open && <ul ref={list} className="pl-formula-suggestions" role="listbox" id={listId} aria-label="Suggestions">
          {options.map((item, index) => <li key={`${item.kind}:${item.value}`} id={`${listId}-${index}`} role="option"
            aria-selected={index === current} className={index === current ? "is-active" : undefined}
            // Choosing with the pointer keeps the caret in the formula.
            onMouseDown={(event) => event.preventDefault()} onClick={() => accept(item)}
            onMouseEnter={() => setActive(index)}>
            <code>{item.kind === "feature" ? formulaName(item.value) : item.value}</code>
            {item.detail && <small>{item.detail}</small>}
          </li>)}
        </ul>}
      </div>
      <span className="ex-sr-only" role="status">
        {open ? `${options.length} ${options.length === 1 ? "suggestion" : "suggestions"}. Use the arrow keys and Enter.` : ""}
      </span>
      <Errors id={`${id}-errors`} issues={errors} onFix={readOnly ? undefined : (fix) => write(fix.start, fix.end, fix.text)} />
      {!readOnly && features.length > 0 && <div className="pl-formula-names" role="group" aria-label="Insert a feature">
        {names.map((feature) => <button type="button" key={feature} title={labels[feature]}
          aria-label={feature === EACH_VARIABLE && each ? "Insert x, each chosen feature" : `Insert ${feature}`}
          onClick={() => insert(feature)}>{feature}</button>)}
      </div>}
      {!features.length && !each && featureHint}
      {help && <small className="pl-help" id={`${id}-help`}>{help}</small>}
    </div>
    {named && <>
      {formula && <div className="pl-field">
        <span id={`${id}-result`}>Result</span>
        <div className="pl-segmented" role="group" aria-labelledby={`${id}-result`}>
          {(["replace", "add"] as const).map((result) => <button key={result} type="button" disabled={readOnly}
            aria-pressed={add === (result === "add")}
            onClick={() => set("result", result === (addsByDefault(component) ? "add" : "replace") ? undefined : result)}>
            {result === "add" ? each ? "Add new features" : "Keep features" : each ? "Replace values" : "Replace features"}
          </button>)}
        </div>
        <small className="pl-help">{outcome}</small>
      </div>}
      {node.component === "prepare.condition" && <p className="pl-help">
        Keeps every observation and adds {name}: 1 when the condition holds, 0 otherwise.
      </p>}
      {each
        ? add && <div className="pl-field">
          <label htmlFor={`${id}-suffix`}>Suffix</label>
          <input id={`${id}-suffix`} value={typeof node.params.suffix === "string" ? node.params.suffix : ""}
            placeholder="formula" maxLength={24} spellCheck={false} autoComplete="off" disabled={readOnly}
            aria-invalid={errorsOf(issues, "suffix").length > 0} aria-describedby={`${id}-suffix-help ${id}-suffix-errors`}
            onChange={(event) => set("suffix", event.target.value || undefined)} />
          <small className="pl-help" id={`${id}-suffix-help`}>Added features are named feature_{suffix}.</small>
          <Errors id={`${id}-suffix-errors`} issues={errorsOf(issues, "suffix")} />
        </div>
        : <CombinedName node={node} component={component} features={features} issues={issues} readOnly={readOnly} onChange={onChange} />}
      {range && <p className="pl-help pl-formula-range"><span>Range</span> {range}</p>}
    </>}
  </div>;
}
