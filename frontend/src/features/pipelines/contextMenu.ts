import type { LucideIcon } from "lucide-react";
import type { PipelineComponent } from "./contracts";
import { familyLabel, STEP_FAMILIES, stepDescription, stepFamily } from "./steps";

export type MenuItem = {
  key: string;
  label: string;
  detail?: string;
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

/** Steps by family, each family opening its steps; typing lists matching steps directly. */
export function stepMenu(
  label: string,
  components: PipelineComponent[],
  pick: (component: PipelineComponent) => void,
  empty: string,
): Menu {
  const entry = (component: PipelineComponent, detail = stepDescription(component)): MenuItem => ({
    key: component.id, label: component.label, detail, run: () => pick(component),
  });
  const familyOf = (component: PipelineComponent) => stepFamily(component.kind, component.id);
  return {
    label,
    empty,
    items: STEP_FAMILIES.flatMap((family) => {
      const steps = components.filter((component) => familyOf(component) === family.id);
      return steps.length ? [{ key: family.id, label: family.label, detail: `${steps.length}`,
        submenu: { label: family.label, items: steps.map((component) => entry(component)) } }] : [];
    }),
    search: {
      label: "Search steps",
      results: (query) => {
        const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
        return STEP_FAMILIES.flatMap((family) => components.filter((component) => familyOf(component) === family.id))
          .filter((component) => {
            const text = `${component.label} ${stepDescription(component)} ${component.description} ${familyLabel(familyOf(component))}`
              .toLocaleLowerCase();
            return words.every((word) => text.includes(word));
          })
          .map((component) => entry(component, familyLabel(familyOf(component))));
      },
    },
  };
}

