// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { PipelineNode } from "@/features/pipelines/contracts";
import { stepScope } from "@/features/pipelines/scope";
import { catalogStep } from "./support/fixtures/pipelines";
import generated from "./support/fixtures/featureNames.generated.json?raw";

/** What the compiler appends to each added feature, written by
 * backend/scripts/generate_pipeline_types.py for each option of every Prepare step. */
type Case = { component: string; params: PipelineNode["params"]; endings: string[] };
const cases = JSON.parse(generated) as Case[];

describe("the names of the features a Prepare step adds", () => {
  it.each(cases.map((item) => [`${item.component} ${JSON.stringify(item.params)}`, item] as const))(
    "%s follows the compiler",
    (_, { component, params, endings }) => {
      const node: PipelineNode = { id: "step", kind: "transform", component, params };
      expect(stepScope(node, catalogStep(component))?.endings).toEqual(endings);
    },
  );
});
