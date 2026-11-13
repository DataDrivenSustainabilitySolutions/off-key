import { ChevronDown } from 'lucide-react';

/** A native, keyboard-accessible select sized to its current value. */
export function ReportingFilter({ label, value, options, active, disabled, onChange }: {
  label: string; value: string; options: readonly { id: string; label: string }[];
  active: boolean; disabled: boolean; onChange: (value: string) => void;
}) {
  return <div className="rp-filter" data-active={active || undefined} data-disabled={disabled || undefined}>
    <span aria-hidden="true">{options.find(option => option.id === value)?.label ?? value}</span>
    <ChevronDown size={12} aria-hidden="true" />
    <select aria-label={label} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      {options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
    </select>
  </div>;
}
