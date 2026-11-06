type Tab<Id extends string> = { id: Id; label: string };

type Props<Id extends string> = {
  name: string;
  idPrefix: string;
  className: string;
  tabs: readonly Tab<Id>[];
  selected: Id;
  onSelect: (id: Id) => void;
};

/** A workspace tab bar with one entry in the sequential focus order. */
export function WorkspaceTabs<Id extends string>({ name, idPrefix, className, tabs, selected, onSelect }: Props<Id>) {
  return <div className={className} role="tablist" aria-label={name}>
    {tabs.map((tab, index) => <button key={tab.id} type="button" role="tab" id={idPrefix + "-tab-" + tab.id}
      aria-selected={tab.id === selected} aria-controls={idPrefix + "-panel"} tabIndex={tab.id === selected ? 0 : -1}
      onClick={() => onSelect(tab.id)}
      onKeyDown={event => {
        const last = tabs.length - 1;
        const directions: Record<string, number> = {
          ArrowLeft: index === 0 ? last : index - 1,
          ArrowRight: index === last ? 0 : index + 1,
          Home: 0,
          End: last,
        };
        const next = tabs[directions[event.key] ?? -1];
        if (!next) return;
        event.preventDefault();
        onSelect(next.id);
        event.currentTarget.ownerDocument.getElementById(idPrefix + "-tab-" + next.id)?.focus();
      }}>{tab.label}</button>)}
  </div>;
}
