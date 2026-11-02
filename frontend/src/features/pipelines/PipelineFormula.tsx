import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { JsonValue } from "@/types/monitoring";
import type { PipelineComponent, PipelineNode } from "./contracts";
import { suggestions, typedWord, type Suggestion } from "./formula";
import { addsByDefault, combinedName, formulaName } from "./scope";

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

/** The name of the feature an Aggregate or Formula computes. */
export function CombinedName({ node, component, issues, readOnly, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  issues: Issue[];
  readOnly?: boolean;
  onChange: Change;
}) {
  const id = useId();
  const errors = errorsOf(issues, "name");
  const set = setter(node, onChange);
  const fallback = combinedName({ ...node, params: { ...node.params, name: null } }, component);
  return <div className="pl-field">
    <label htmlFor={`${id}-name`}>Name</label>
    <input id={`${id}-name`} value={typeof node.params.name === "string" ? node.params.name : ""}
      placeholder={fallback} maxLength={120} spellCheck={false} autoComplete="off" disabled={readOnly}
      aria-invalid={errors.length > 0} aria-describedby={`${id}-name-help ${id}-name-errors`}
      onChange={(event) => set("name", event.target.value || undefined)} />
    <small className="pl-help" id={`${id}-name-help`}>
      The computed feature, in letters, digits and underscores. Leave empty for {fallback}.
    </small>
    <Errors id={`${id}-name-errors`} issues={errors} />
  </div>;
}

/** A Formula's expression or a Gate's condition, written over the features that arrive. */
export function PipelineFormula({ node, component, features, featureLabels, issues, readOnly, range, onChange }: {
  node: PipelineNode;
  component: PipelineComponent;
  /** Incoming feature names in their order, once the graph has been checked. */
  features: string[];
  featureLabels: Record<string, string>;
  issues: Issue[];
  readOnly?: boolean;
  /** The values the computed feature can take, as the check inferred them. */
  range?: string;
  onChange: Change;
}) {
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const gate = node.component === "prepare.gate";
  const field = gate ? "condition" : "expression";
  const text = typeof node.params[field] === "string" ? node.params[field] : "";
  const errors = errorsOf(issues, field);
  const set = setter(node, onChange);
  const help = component.fields.find((item) => item.name === field)?.description;
  // The caret while the field has focus and nothing is selected; suggestions follow it.
  const [caret, setCaret] = useState<number>();
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState<string>();
  const word = caret === undefined || readOnly ? undefined : typedWord(text, caret);
  const key = word && `${word.start}:${word.prefix}`;
  const options = word && key !== dismissed ? suggestions(word, features, featureLabels, gate) : [];
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
    // A function opens its parentheses, and the caret goes between them.
    const called = text[word.end] === "(";
    write(word.start, word.end, called ? item.value : `${item.value}()`, item.value.length + 1);
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
  return <div className="pl-formula">
    <div className="pl-field">
      <label htmlFor={`${id}-text`}>{gate ? "Condition" : "Formula"}</label>
      <div className="pl-formula-input">
        <textarea ref={area} id={`${id}-text`} className="pl-code" rows={3} maxLength={512} value={text}
          placeholder={gate ? "dc_current > 1" : "dc_voltage * dc_current"} disabled={readOnly}
          spellCheck={false} autoComplete="off" autoCapitalize="off" autoCorrect="off"
          aria-invalid={errors.length > 0} aria-describedby={`${id}-errors ${id}-help`}
          aria-autocomplete="list" aria-controls={open ? listId : undefined}
          aria-activedescendant={open ? `${listId}-${current}` : undefined}
          onChange={(event) => {
            set(field, event.target.value);
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
        {features.map((feature) => <button type="button" key={feature} title={featureLabels[feature]}
          aria-label={`Insert ${feature}`} onClick={() => insert(feature)}>{feature}</button>)}
      </div>}
      {help && <small className="pl-help" id={`${id}-help`}>{help}</small>}
    </div>
    {!gate && <>
      <div className="pl-field">
        <span id={`${id}-result`}>Result</span>
        <div className="pl-segmented" role="group" aria-labelledby={`${id}-result`}>
          {(["replace", "add"] as const).map((result) => <button key={result} type="button" disabled={readOnly}
            aria-pressed={add === (result === "add")}
            onClick={() => set("result", result === (addsByDefault(component) ? "add" : "replace") ? undefined : result)}>
            {result === "add" ? "Keep features" : "Replace features"}
          </button>)}
        </div>
        <small className="pl-help">
          {add ? `Keeps the features and adds ${name}.` : `Replaces the features the formula reads with ${name}.`}
        </small>
      </div>
      <CombinedName node={node} component={component} issues={issues} readOnly={readOnly} onChange={onChange} />
      {range && <p className="pl-help pl-formula-range"><span>Range</span> {range}</p>}
    </>}
  </div>;
}
