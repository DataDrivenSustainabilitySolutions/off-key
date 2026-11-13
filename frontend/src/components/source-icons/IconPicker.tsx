import { useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown, RotateCcw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SOURCE_COLORS, type SourceAppearance } from "@/types/source-appearance";
import { getErrorMessage } from "@/lib/errors";
import { SOURCE_ICON_GROUPS, sourceIcon, type SourceIconKind } from "./catalogue";
import { SourceIcon } from "./SourceIcon";
import "./icon-picker.css";

type Props = {
  kind: SourceIconKind;
  label: string;
  value?: SourceAppearance;
  color?: string;
  disabled?: boolean;
  badge?: boolean;
  onChange: (value: SourceAppearance | undefined) => void | boolean | Promise<boolean>;
};

export function IconPicker({ kind, label, value, color, disabled, badge, onChange }: Props) {
  const [open, setOpen] = useState(false);
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <Popover.Trigger asChild><button type="button" className={`source-icon-trigger${badge ? " source-icon-trigger--badge" : ""}`}
      disabled={disabled} aria-label={`Change icon for ${label}`} title="Change icon and color">
      <SourceIcon kind={kind} appearance={value} color={color} size={badge ? 22 : 18} />
      {!badge && <><span>{sourceIcon(kind, value?.icon).label}</span><ChevronDown size={13} aria-hidden="true" /></>}
    </button></Popover.Trigger>
    {open && <PickerContent kind={kind} label={label} value={value} color={color} disabled={disabled}
      onChange={onChange} onClose={() => setOpen(false)} />}
  </Popover.Root>;
}

function PickerContent({ kind, label, value, color, disabled, onChange, onClose }: Props & { onClose: () => void }) {
  const [draft, setDraft] = useState<SourceAppearance>(value ?? {});
  // Keep the opening catalogue revision so a concurrent edit cannot be overwritten.
  const [save] = useState(() => onChange);
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const search = useRef<HTMLInputElement>(null);
  const selected = sourceIcon(kind, draft.icon);
  const words = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  const groups = SOURCE_ICON_GROUPS.map(group => ({ ...group, icons: group.icons.filter(icon =>
    words.every(word => `${icon.label} ${icon.keywords}`.toLocaleLowerCase().includes(word))) })).filter(group => group.icons.length);
  const apply = async () => {
    if (busy.current || disabled) return;
    busy.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await save(Object.keys(draft).length ? draft : undefined);
      if (result === false) setError("The icon was not saved. Review the current catalogue and try again.");
      else onClose();
    } catch (failure) { setError(getErrorMessage(failure)); }
    finally { busy.current = false; setSaving(false); }
  };
  return <Popover.Portal><Popover.Content className="icon-picker" align="start" sideOffset={8} collisionPadding={12}
    aria-label="Icon and color" onOpenAutoFocus={event => { event.preventDefault(); search.current?.focus(); }}
    onEscapeKeyDown={event => { if (busy.current) event.preventDefault(); }}
    onInteractOutside={event => { if (busy.current) event.preventDefault(); }}>
    <header className="icon-picker-heading"><div><h3>Icon & color</h3><p title={label}>{label}</p></div>
      <button type="button" className="icon-picker-close" aria-label="Close icon picker" onClick={onClose} disabled={saving}><X size={16} aria-hidden="true" /></button>
    </header>
    <fieldset disabled={saving || disabled}><div className="icon-picker-fields">
      <div className="icon-picker-preview"><SourceIcon kind={kind} appearance={draft} color={color} size={20} />
        <span>{selected.label}<small>{draft.color ? draft.color[0]!.toUpperCase() + draft.color.slice(1) : "Default color"}</small></span>
        <button type="button" onClick={() => { setDraft({}); setError(""); }} title="Restore default icon and color" aria-label="Reset icon and color"><RotateCcw size={14} aria-hidden="true" />Reset</button>
      </div>
      <div className="icon-picker-colors" role="group" aria-label="Icon color">
        {[undefined, ...SOURCE_COLORS].map(tone => <button key={tone ?? "default"} type="button" className="icon-picker-swatch"
          data-color={tone} aria-label={tone ? `${tone[0]!.toUpperCase()}${tone.slice(1)} color` : "Default color"}
          title={tone ? `${tone[0]!.toUpperCase()}${tone.slice(1)}` : "Default color"} aria-pressed={draft.color === tone}
          onClick={() => setDraft(current => { const next = { ...current }; if (tone) next.color = tone; else delete next.color; return next; })}>
          <span>{draft.color === tone && <Check size={12} strokeWidth={2.5} aria-hidden="true" />}</span>
        </button>)}
      </div>
      <label className="icon-picker-search"><Search size={15} aria-hidden="true" /><input ref={search} type="search" aria-label="Search icons"
        placeholder="Search icons…" value={query} onChange={event => setQuery(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter") event.preventDefault(); }} /></label>
      <div className="icon-picker-library">
        {groups.map(group => <section key={group.label} aria-label={group.label}><h4>{group.label}</h4>
          <div className="icon-picker-grid">{group.icons.map(icon => <button type="button" key={icon.id} aria-label={`${icon.label} icon`}
            title={icon.label} aria-pressed={selected.id === icon.id} onClick={() => setDraft(current => ({ ...current, icon: icon.id }))}>
            <SourceIcon kind={kind} appearance={{ ...draft, icon: icon.id }} size={18} />
            <span className="icon-picker-label" aria-hidden="true">{icon.label}</span>
          </button>)}</div>
        </section>)}
        {!groups.length && <p className="icon-picker-empty" role="status">No icons match “{query}”. Try sensor, motor, or temperature.</p>}
      </div>
    </div></fieldset>
    {error && <p className="icon-picker-error" role="alert">{error}</p>}
    <footer className="icon-picker-actions"><Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
      <Button type="button" size="sm" onClick={() => void apply()} disabled={saving || disabled}>{saving ? "Saving…" : "Apply"}</Button></footer>
  </Popover.Content></Popover.Portal>;
}
