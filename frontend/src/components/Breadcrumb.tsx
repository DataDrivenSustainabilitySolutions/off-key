type Step = { label: string; onClick: () => void };

/** Where a detail view sits, with every level above it one click away. */
export function Breadcrumb({ steps, current, disabled = false }: { steps: Step[]; current: string; disabled?: boolean }) {
  return <nav className="ex-breadcrumb" aria-label="Breadcrumb"><ol>
    {steps.map(step => <li key={step.label}><button type="button" disabled={disabled} onClick={step.onClick}>{step.label}</button></li>)}
    <li aria-current="page" title={current}>{current}</li>
  </ol></nav>;
}
