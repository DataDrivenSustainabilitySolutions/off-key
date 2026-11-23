import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import { retitle, stepOrder, type GraphDocument } from "@/features/pipelines/model";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { asServedList } from "./support/fixtures/pipelines";

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: asServedList([
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "The chosen readings as one observation.",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "Hands features on as they are.",
      details: "A place to branch from.", input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "Scores each observation.",
      input_type: "features", output_type: "scores" },
  ]),
});

/** The detector is listed first and comes last, so the order shown is the order the data flows in. */
const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "detector", kind: "detector", component: "detector:a" },
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "pass", kind: "transform", component: "features.passthrough" },
    ],
    edges: [{ source: "input", target: "pass", order: 0 }, { source: "pass", target: "detector", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, pass: { x: 288, y: 0 }, detector: { x: 576, y: 0 } } }),
});

let shown: GraphDocument;
function Settings({ start = "pass", readOnly = false }: { start?: string; readOnly?: boolean }) {
  const [document, setDocument] = useState(design);
  const [selected, setSelected] = useState<string | undefined>(start);
  return <>
    <PipelineInspector document={document} catalog={catalog} selected={selected} readOnly={readOnly}
      onSelect={setSelected} onChange={(next) => { shown = next; setDocument(next); }} />
    {/* Stands in for a card on the canvas: a step chosen there, not in the settings. */}
    <button type="button" onClick={() => setSelected("input")}>Input card</button>
  </>;
}

beforeEach(() => { shown = design(); });

const heading = () => screen.getByRole("heading", { level: 3 }).textContent;
const jump = () => screen.getByRole<HTMLSelectElement>("combobox", { name: "Selected step" });
const tab = (name: string) => screen.getByRole("tab", { name: new RegExp(`^${name}`) });
const title = (id: string) => shown.definition.nodes.find((node) => node.id === id)!.label;

describe("the order of steps", () => {
  it("follows the data, wherever the cards stand", () => {
    expect(stepOrder(design())).toEqual(["input", "pass", "detector"]);
    const wrapped = design();
    wrapped.layout.nodes.detector = { x: 0, y: 200 };
    expect(stepOrder(wrapped)).toEqual(["input", "pass", "detector"]);
  });

  it("takes the leftmost of the steps that could come next, and the upper one of two in a column", () => {
    const branched = design();
    branched.definition.nodes.push({ ...branched.definition.nodes.find((node) => node.id === "pass")!, id: "other" },
      { ...branched.definition.nodes.find((node) => node.id === "pass")!, id: "loose" });
    branched.definition.edges.push({ source: "input", target: "other", order: 0 });
    branched.layout.nodes.other = { x: 288, y: 200 };
    branched.layout.nodes.loose = { x: 900, y: 0 };
    expect(stepOrder(branched)).toEqual(["input", "pass", "other", "detector", "loose"]);
    branched.layout.nodes.other = { x: 100, y: 200 };
    expect(stepOrder(branched)).toEqual(["input", "other", "pass", "detector", "loose"]);
  });

  it("keeps steps that feed each other in their places", () => {
    const circle = design();
    circle.definition.edges.push({ source: "detector", target: "pass", order: 1 });
    expect(stepOrder(circle)).toEqual(["input", "pass", "detector"]);
  });
});

describe("a step's title", () => {
  it("is kept trimmed, and is dropped when it is the step's own name or empty", () => {
    const named = retitle(design(), catalog.components, "pass", "  Branch  ")!;
    expect(named.definition.nodes.find((node) => node.id === "pass")!.label).toBe("Branch");
    expect(retitle(named, catalog.components, "pass", "Branch")).toBeUndefined();
    expect(retitle(named, catalog.components, "pass", "Pass through")!.definition.nodes.find((node) => node.id === "pass")!.label)
      .toBeUndefined();
    expect(retitle(design(), catalog.components, "pass", " ")).toBeUndefined();
    expect(retitle(design(), catalog.components, "gone", "Branch")).toBeUndefined();
  });
});

describe("the head of a step's settings", () => {
  it("names the step, says what it does and where it stands", () => {
    render(<Settings />);
    expect(heading()).toBe("Pass through");
    expect(screen.getByText("Route")).toBeTruthy();
    expect(screen.getByText("Hands features on as they are.")).toBeTruthy();
    expect(within(screen.getByRole("group", { name: "Steps" })).getByText("2 of 3")).toBeTruthy();
    expect([...jump().options].map((option) => option.textContent)).toEqual(["Aligned inputs", "Pass through", "Detector A"]);
  });

  it("goes to the step before, the step after and straight to any step", () => {
    render(<Settings />);
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(heading()).toBe("Detector A");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Next step" }).disabled).toBe(true);
    fireEvent.change(jump(), { target: { value: "input" } });
    expect(heading()).toBe("Aligned inputs");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Previous step" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(heading()).toBe("Pass through");
  });

  it("renames the step where its name stands", () => {
    render(<Settings />);
    fireEvent.click(screen.getByRole("button", { name: "Rename step" }));
    const field = screen.getByRole<HTMLInputElement>("textbox", { name: "Step title" });
    expect(field.value).toBe("Pass through");
    fireEvent.change(field, { target: { value: "Branch" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(heading()).toBe("Branch");
    expect(title("pass")).toBe("Branch");
    // Under a title of its own, the step still says what it is.
    expect(screen.getByText("Pass through")).toBeTruthy();

    // Escape keeps the title it had.
    fireEvent.doubleClick(screen.getByRole("heading", { level: 3 }));
    fireEvent.change(screen.getByRole("textbox", { name: "Step title" }), { target: { value: "Other" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Step title" }), { key: "Escape" });
    expect(heading()).toBe("Branch");
    expect(title("pass")).toBe("Branch");
  });

  it("duplicates, disconnects and removes the step from its menu", () => {
    render(<Settings />);
    const open = () => {
      fireEvent.click(screen.getByRole("button", { name: "Step actions" }));
      return within(screen.getByRole("menu"));
    };
    fireEvent.click(open().getByRole("menuitem", { name: /^Duplicate/ }));
    expect(shown.definition.nodes).toHaveLength(4);
    // The copy is the step in focus.
    expect(jump().value).not.toBe("pass");
    fireEvent.change(jump(), { target: { value: "pass" } });

    fireEvent.click(open().getByRole("menuitem", { name: /^Disconnect/ }));
    expect(shown.definition.edges.some((edge) => edge.source === "pass" || edge.target === "pass")).toBe(false);
    expect(open().getByRole("menuitem", { name: /^Disconnect/ }).getAttribute("aria-disabled")).toBe("true");
    fireEvent.keyDown(screen.getByRole("menu").closest(".pl-context-menu")!, { key: "Escape" });

    fireEvent.click(open().getByRole("menuitem", { name: /^Remove step/ }));
    expect(shown.definition.nodes.some((node) => node.id === "pass")).toBe(false);
  });

  it("offers no changes where the design is only shown", () => {
    render(<Settings readOnly />);
    expect(screen.queryByRole("button", { name: "Rename step" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Step actions" })).toBeNull();
    expect(screen.getByRole("button", { name: "Next step" })).toBeTruthy();
  });

  it("lists the steps to choose from while none is chosen", () => {
    render(<Settings start="" />);
    expect(heading()).toBe("Step settings");
    expect(jump().value).toBe("");
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(within(steps).getAllByRole("button").map((button) => button.textContent))
      .toEqual(["Aligned inputs", "Pass through", "Detector A"]);
    fireEvent.click(within(steps).getByRole("button", { name: "Detector A" }));
    expect(heading()).toBe("Detector A");
  });
});

describe("the parts of a step's settings", () => {
  it("keeps what flows through the step and what the step is apart from its settings", () => {
    render(<Settings />);
    expect(tab("Settings").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("This step has nothing to set.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Incoming connections" })).toBeNull();

    fireEvent.click(tab("Data"));
    expect(within(screen.getByRole("list", { name: "Incoming connections" })).getByText("Aligned inputs")).toBeTruthy();
    expect(screen.getByText("Features to Detector A")).toBeTruthy();

    fireEvent.click(tab("About"));
    expect(screen.getByText("A place to branch from.")).toBeTruthy();
    expect(screen.getByText("Takes features and gives features.")).toBeTruthy();
  });

  it("moves between the parts with the arrow keys", () => {
    render(<Settings />);
    fireEvent.keyDown(tab("Settings"), { key: "ArrowRight" });
    expect(tab("Data").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab("Data"));
    fireEvent.keyDown(tab("Data"), { key: "ArrowLeft" });
    fireEvent.keyDown(tab("Settings"), { key: "ArrowLeft" });
    expect(tab("About").getAttribute("aria-selected")).toBe("true");
  });

  it("follows one part from step to step, and opens a step chosen elsewhere at its settings", () => {
    render(<Settings />);
    fireEvent.click(tab("Data"));
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(heading()).toBe("Detector A");
    expect(tab("Data").getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Input card" }));
    expect(heading()).toBe("Aligned inputs");
    expect(tab("Settings").getAttribute("aria-selected")).toBe("true");
  });
});
