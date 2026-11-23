import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizeCatalog, normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import type { GraphDocument } from "@/features/pipelines/model";
import type PipelineCanvas from "@/features/pipelines/PipelineCanvas";
import { PipelineInspector } from "@/features/pipelines/PipelineInspector";
import { PipelineWorkbench } from "@/features/pipelines/PipelineWorkbench";
import { asServedList } from "./support/fixtures/pipelines";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));
vi.mock("@/features/pipelines/PipelineCanvas", () => ({
  default: (props: ComponentProps<typeof PipelineCanvas>) => <button type="button" onClick={() => props.onSelect("pass")}>
    Pass card</button>,
}));

const catalog = normalizeCatalog({
  catalog_id: "test", authoring_enabled: true, templates: [], components: asServedList([
    { id: "source.aligned", kind: "source", group: "input", label: "Aligned inputs", description: "The chosen readings.",
      input_type: null, output_type: "features" },
    { id: "features.passthrough", kind: "transform", group: "route", label: "Pass through", description: "Hands features on.",
      details: "A place to branch from.", input_type: "features", output_type: "features" },
    { id: "detector:a", kind: "detector", group: "detector", label: "Detector A", description: "Scores each observation.",
      input_type: "features", output_type: "scores" },
  ]),
});

const design = (): GraphDocument => ({
  definition: normalizeDefinition({
    input_slots: [{ id: "value", label: "Value" }],
    nodes: [
      { id: "input", kind: "source", component: "source.aligned" },
      { id: "pass", kind: "transform", component: "features.passthrough" },
      { id: "detector", kind: "detector", component: "detector:a" },
    ],
    edges: [{ source: "input", target: "pass", order: 0 }, { source: "pass", target: "detector", order: 0 }],
  }),
  layout: normalizeLayout({ nodes: { input: { x: 0, y: 0 }, pass: { x: 288, y: 0 }, detector: { x: 576, y: 0 } } }),
});

const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

describe("a step's settings in a drawer", () => {
  it("show what arrives and what leaves on either side of the settings", () => {
    render(<PipelineInspector document={design()} catalog={catalog} selected="pass" layout="drawer"
      onSelect={() => {}} onChange={() => {}} />);
    expect(within(screen.getByRole("region", { name: "Arrives" })).getByText("Aligned inputs")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Leaves" })).getByText(/to Detector A$/)).toBeTruthy();
    expect(tabs()).toEqual(["Settings", "About"]);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Settings" }), { key: "ArrowRight" });
    expect(screen.getByText("A place to branch from.")).toBeTruthy();
  });

  it("keep their part from step to step, and open at the settings where the part is not theirs", () => {
    function Settings({ layout }: { layout: "side" | "drawer" }) {
      const [selected, setSelected] = useState<string | undefined>("pass");
      return <PipelineInspector document={design()} catalog={catalog} selected={selected} layout={layout}
        onSelect={setSelected} onChange={() => {}} />;
    }
    const view = render(<Settings layout="side" />);
    fireEvent.click(screen.getByRole("tab", { name: /^Data/ }));
    view.rerender(<Settings layout="drawer" />);
    expect(screen.getByRole("tab", { name: "Settings" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "About" }));
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("tab", { name: "About" }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("where the workbench opens a step's settings", () => {
  const original = window.matchMedia;
  afterEach(() => { window.matchMedia = original; });
  const onPhone = (matches: boolean) => {
    window.matchMedia = (media: string) => ({ ...original(media), matches: matches && media === "(max-width: 680px)" });
  };
  function Composer() {
    const [selected, setSelected] = useState<string>();
    return <PipelineWorkbench catalog={catalog} document={design()} selected={selected} onSelect={setSelected}
      onChange={() => {}} onAdd={() => {}} />;
  }
  const open = () => {
    render(<Composer />);
    fireEvent.click(screen.getByRole("button", { name: "Pass card" }));
  };

  it("is a drawer under the canvas that can be pulled taller or shorter", () => {
    onPhone(false);
    open();
    const grip = screen.getByRole("separator", { name: "Resize step settings" });
    const drawer = grip.parentElement!;
    expect(drawer.style.height).toBe("340px");
    fireEvent.keyDown(grip, { key: "ArrowUp" });
    expect(grip.getAttribute("aria-valuenow")).toBe("364");
    expect(drawer.style.height).toBe("364px");
    fireEvent.keyDown(grip, { key: "Home" });
    expect(drawer.style.height).toBe("200px");
    fireEvent.keyDown(grip, { key: "ArrowDown" });
    expect(drawer.style.height).toBe("200px");
  });

  it("is a sheet with one part at a time on a phone", () => {
    onPhone(true);
    open();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.queryByRole("region", { name: "Arrives" })).toBeNull();
    expect(tabs().map((tab) => tab?.match(/^(Settings|Data|About)/)?.[0])).toEqual(["Settings", "Data", "About"]);
  });
});
