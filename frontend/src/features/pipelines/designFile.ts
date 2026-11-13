import { ApiRequestError } from "@/lib/api-client";
import { DESIGN_FILE, type PipelineDefinition as WireDefinition, type PipelineDesignFile } from "@/types/pipelines.generated";
import { pipelinesApi } from "./api";
import { normalizeLayout, type PipelineDefinition, type PipelineLayout, type PipelineValidation } from "./contracts";
import { arrangeGraph } from "./layout";
import type { GraphDocument } from "./model";
import { readNotes } from "./notes";
import { PASS_THROUGH, switchedOff } from "./semantics";

/** A design is a small document; a larger file is something else. */
export const MAX_DESIGN_BYTES = 1_048_576;

export type OpenedDesign = { document: GraphDocument; name: string; description: string };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, limit: number) => (typeof value === "string" ? value.trim().slice(0, limit) : "");

/** A design as the text of a file, in the format the documentation publishes. */
export function writeDesign(document: GraphDocument, name: string, description: string): string {
  const { definition, layout } = document;
  const off = Object.fromEntries(definition.nodes.flatMap((node) => {
    const was = switchedOff(layout, node);
    return was ? [[node.id, was]] : [];
  }));
  const file: PipelineDesignFile = {
    $schema: DESIGN_FILE.schema, format: DESIGN_FILE.format, schema_version: DESIGN_FILE.version,
    name: name.trim(), description: description.trim(), definition,
    // Only the cards of this design; places a removed step left behind stay out of the file.
    layout: { nodes: Object.fromEntries(definition.nodes.flatMap((node) => {
      const at = layout.nodes[node.id];
      return at ? [[node.id, at]] : [];
    })), ...(Object.keys(off).length ? { switched_off: off } : {}), ...(layout.notes?.length ? { notes: layout.notes } : {}) },
  };
  return `${JSON.stringify(file, null, 2)}\n`;
}

/** "Equipment health" is saved as equipment-health.design.json. */
export const designFileName = (name: string) =>
  `${name.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 60) || "design"}.design.json`;

/** Hand the design to the browser as a download, and say what the file is called. */
export function downloadDesign(document: GraphDocument, name: string, description: string) {
  const url = URL.createObjectURL(new Blob([writeDesign(document, name, description)], { type: "application/json" }));
  const link = window.document.createElement("a");
  link.href = url; link.download = designFileName(name); link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return link.download;
}

/** The parts of a design file, or an error that says why the text is none. */
function parseDesign(contents: string) {
  let value: unknown;
  try { value = JSON.parse(contents); } catch { throw new Error("This file is not a design: it does not hold JSON."); }
  if (!isRecord(value) || value.format !== DESIGN_FILE.format)
    throw new Error(`This file is not a design. A design file says "format": "${DESIGN_FILE.format}".`);
  if (value.schema_version !== undefined && value.schema_version !== DESIGN_FILE.version)
    throw new Error("This design file was written in a newer format than this version reads.");
  if (!isRecord(value.definition)) throw new Error("This design file holds no definition of its steps.");
  if (value.definition.schema_version !== 2)
    throw new Error('The design in this file cannot be read. A design says "schema_version": 2.');
  return { name: text(value.name, 120), description: text(value.description, 2000),
    definition: value.definition as WireDefinition, layout: value.layout };
}

/** Where the file puts each card and what it calls it; whether every card has a place. */
function drawn(definition: PipelineDefinition, layout: unknown): { layout: PipelineLayout; complete: boolean } {
  const given = isRecord(layout) && isRecord(layout.nodes) ? layout.nodes : {};
  let complete = true;
  const nodes = Object.fromEntries(definition.nodes.map((node) => {
    const at = given[node.id];
    const placed = isRecord(at) && typeof at.x === "number" && typeof at.y === "number"
      && Number.isFinite(at.x) && Number.isFinite(at.y) ? { x: at.x, y: at.y } : undefined;
    if (!placed) complete = false;
    // A step may carry its title itself, so a file can name a step without placing it.
    const title = text(isRecord(at) ? at.label : undefined, 120) || text(node.label, 120);
    return [node.id, { x: 0, y: 0, ...placed, ...(title ? { label: title } : {}) }];
  }));
  // What a switched-off step was, for the steps that stand aside in this design.
  const remembered = isRecord(layout) && isRecord(layout.switched_off) ? layout.switched_off : {};
  const off = Object.fromEntries(definition.nodes.flatMap((node) => {
    const was = node.component === PASS_THROUGH ? remembered[node.id] : undefined;
    return isRecord(was) && typeof was.component === "string" && was.component && isRecord(was.params)
      ? [[node.id, { component: was.component, contract_version: Number.isInteger(was.contract_version) ? was.contract_version as number : 1,
        params: was.params }]] : [];
  }));
  const notes = readNotes(isRecord(layout) ? layout.notes : undefined);
  return { layout: normalizeLayout({ nodes, ...(Object.keys(off).length ? { switched_off: off } : {}), ...(notes.length ? { notes } : {}) }),
    complete };
}

/**
 * Read a design from the text of a file. The server reads the definition as it reads one sent
 * through the API, so a malformed one is refused with the reason. Steps the file does not place
 * are arranged.
 */
export async function openDesign(
  contents: string,
  check: (definition: WireDefinition) => Promise<PipelineValidation> = (definition) => pipelinesApi.validate(definition),
): Promise<OpenedDesign> {
  const file = parseDesign(contents);
  const answer = await check(file.definition).then((report) => ({ report }), (reason: unknown) => ({ reason }));
  if ("reason" in answer) {
    const { reason } = answer;
    // Only a refusal of the design is about the file; a lost connection is not.
    if (!(reason instanceof ApiRequestError) || reason.status !== 422) throw reason;
    const issues = reason.issues.map((issue) => `${issue.loc.filter((part) => part !== "body").join(".")}: ${issue.msg}`);
    const shown = issues.length ? `${issues.slice(0, 3).join("; ")}${issues.length > 3 ? `; and ${issues.length - 3} more` : ""}` : reason.message;
    throw new Error(`The design in this file cannot be read. ${shown}`);
  }
  const { report } = answer;
  // The canvas tells steps apart by their id.
  const ids = report.definition.nodes.map((node) => node.id);
  const twice = ids.find((id, index) => ids.indexOf(id) !== index);
  if (twice) throw new Error(`The design in this file cannot be read. Two of its steps have the id "${twice}".`);
  const { layout, complete } = drawn(report.definition, file.layout);
  return { name: file.name, description: file.description,
    document: { definition: report.definition, layout: complete ? layout : await arrangeGraph(report.definition, layout) } };
}

/** Read a design from a file the operator chose or dropped. */
export async function openDesignFile(file: File): Promise<OpenedDesign> {
  if (file.size > MAX_DESIGN_BYTES) throw new Error("This file is too large to be a design.");
  const design = await openDesign(await file.text());
  // A design without a name takes the name of its file.
  return design.name ? design : { ...design, name: file.name.replace(/(\.design)?\.json$/i, "").slice(0, 120) };
}
