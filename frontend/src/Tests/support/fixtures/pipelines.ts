import { normalizeCatalog, type PipelineComponent } from "@/features/pipelines/contracts";
import type * as Wire from "@/types/pipelines.generated";
import served from "./pipelineCatalog.generated.json?raw";

type Kind = PipelineComponent["kind"];
type Group = PipelineComponent["group"];

const GROUPS: Record<Kind, Group> = {
  source: "input", transform: "prepare", merge: "route", detector: "detector",
  calibration: "calibration", policy: "policy", output: "output",
};

/** The group a hand-built step of this kind has, where the test does not depend on it.
 * A test about a step's place in the menu names the group itself, as the catalog does. */
export const groupOf = (kind: Kind): Group => GROUPS[kind];

/** The catalog the API serves, as backend/scripts/generate_pipeline_types.py writes it.
 * A step the backend changes changes this file, and CI fails while it is stale. */
const servedCatalog = normalizeCatalog(JSON.parse(served) as Wire.PipelineCatalog);

/** A real step as the catalog serves it, a copy each test may change. */
export function catalogStep(id: string): PipelineComponent {
  const component = servedCatalog.components.find((item) => item.id === id);
  if (!component) throw new Error(`${id} is not in the generated catalog`);
  return structuredClone(component);
}

/** What a step does in a design, which a hand-built copy must state as the catalog does.
 * Labels and help are left out: a test may name a step as it likes. */
const STEP_FACTS = ["kind", "group", "learning", "counterpart", "input_type", "output_type"] as const;
const FIELD_FACTS = [
  "type", "default", "required", "nullable", "options", "minimum", "maximum",
  "exclusive_minimum", "exclusive_maximum", "shown_when",
] as const;
type Stated = {
  id: string;
  fields?: ReadonlyArray<{ name: string } & Partial<Record<(typeof FIELD_FACTS)[number], unknown>>>;
} & Partial<Record<(typeof STEP_FACTS)[number], unknown>>;

/** A fact as the catalog means it: a key it leaves out holds its empty default. */
const meaning = (fact: string, value: unknown): unknown => {
  if (value === undefined || value === null) return fact === "required" || fact === "nullable" ? false : null;
  return typeof value === "object" && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).filter(([, item]) => item !== null)) : value;
};
const differs = (fact: string, stated: unknown, served: unknown) =>
  JSON.stringify(meaning(fact, stated)) !== JSON.stringify(meaning(fact, served));

/** Where a real step sits and what it takes and gives, for a hand-built copy to start
 * from instead of guessing them from its kind. A test's own step gets nothing. */
export function servedShape(id: string): Partial<Pick<PipelineComponent, "group" | "input_type" | "output_type">> {
  const served = servedCatalog.components.find((item) => item.id === id);
  return served ? { group: served.group, input_type: served.input_type, output_type: served.output_type } : {};
}

/** A hand-built copy of a real step, checked against the catalog the API serves.
 * It may leave facts and settings out; what it states must match, so a step the
 * backend changes fails the test that copied it. An id the catalog lacks is a
 * test's own step and is returned as it is. */
export function asServed<T extends Stated>(component: T): T {
  const served = servedCatalog.components.find((item) => item.id === component.id);
  if (!served) return component;
  const wrong = STEP_FACTS.filter((fact) => fact in component && differs(fact, component[fact], served[fact]))
    .map((fact) => `${fact} ${JSON.stringify(component[fact])} (served: ${JSON.stringify(served[fact])})`);
  for (const field of component.fields ?? []) {
    const real = served.fields.find((item) => item.name === field.name);
    if (!real) { wrong.push(`setting ${field.name} (not served)`); continue; }
    for (const fact of FIELD_FACTS) {
      if (fact in field && differs(fact, field[fact], real[fact]))
        wrong.push(`${field.name}.${fact} ${JSON.stringify(field[fact])} (served: ${JSON.stringify(real[fact])})`);
    }
  }
  if (wrong.length) throw new Error(`${component.id} differs from the generated catalog: ${wrong.join("; ")}`);
  return component;
}

/** A hand-built catalog list, each real step in it checked as {@link asServed} does. */
export const asServedList = <T extends Stated = Wire.PipelineComponent>(components: NoInfer<T>[]): T[] =>
  components.map(asServed);
