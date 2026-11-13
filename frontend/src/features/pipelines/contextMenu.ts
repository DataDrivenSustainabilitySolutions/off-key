import type { LucideIcon } from "lucide-react";
import type { PipelineComponent } from "./contracts";
import { familyLabel, STEP_FAMILIES } from "./steps";

export type MenuItem = {
  key: string;
  label: string;
  detail?: string;
  /** What the entry does, in full. Shown below the list while the entry is in focus. */
  help?: string;
  icon?: LucideIcon;
  /** Why the entry cannot be chosen; it stays listed so the reason can be read. */
  blocked?: string;
  destructive?: boolean;
  /** Starts a new group below a line. */
  separated?: boolean;
  run?: () => void;
  submenu?: Menu;
};

export type Menu = {
  label: string;
  items: MenuItem[];
  /** Typing narrows a searchable menu to the entries this returns. */
  search?: { label: string; results: (query: string) => MenuItem[] };
  /** Shown when there is nothing to list. */
  empty?: string;
};

/** Steps by family, each family opening its steps; typing lists matching steps directly.
 * Saved blocks follow the families as one more group. */
export function stepMenu(
  label: string,
  components: PipelineComponent[],
  pick: (component: PipelineComponent) => void,
  empty: string,
  blocks: MenuItem[] = [],
): Menu {
  const entry = (component: PipelineComponent, detail = component.description): MenuItem => ({
    key: component.id, label: component.label, detail, run: () => pick(component),
  });
  return {
    label,
    empty,
    items: [
      ...STEP_FAMILIES.flatMap((family) => {
        const steps = components.filter((component) => component.group === family.id);
        return steps.length ? [{ key: family.id, label: family.label, detail: `${steps.length}`,
          submenu: { label: family.label, items: steps.map((component) => entry(component)) } }] : [];
      }),
      ...(blocks.length ? [{ key: "blocks", label: "Blocks", detail: `${blocks.length}`, separated: true,
        submenu: { label: "Blocks", items: blocks } }] : []),
    ],
    search: {
      label: "Search steps",
      results: (query) => {
        const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
        const matches = (text: string) => words.every((word) => text.toLocaleLowerCase().includes(word));
        return [
          ...STEP_FAMILIES.flatMap((family) => components.filter((component) => component.group === family.id))
            .filter((component) => matches(`${component.label} ${component.description} ${familyLabel(component.group)}`))
            .map((component) => entry(component, familyLabel(component.group))),
          ...blocks.filter((block) => matches(`${block.label} ${block.detail ?? ""} block`))
            .map((block) => ({ ...block, detail: "Block" })),
        ];
      },
    },
  };
}
