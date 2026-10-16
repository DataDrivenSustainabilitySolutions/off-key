import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelineEditor from "@/features/pipelines/PipelineEditor";
import {
  normalizeCatalog,
  normalizeDefinition,
  normalizeLayout,
  normalizeView,
} from "@/features/pipelines/contracts";
import { pipelinesApi } from "@/features/pipelines/api";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import { ApiRequestError } from "@/lib/api-client";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1 }) }));
vi.mock("@/components/theme-provider", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));
vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: {
    get: vi.fn(),
    save: vi.fn(),
    metadata: vi.fn(),
    validate: vi.fn(),
    publish: vi.fn(),
    create: vi.fn(),
  },
}));

const definition = normalizeDefinition({
  strategy: "adaptive_stream",
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "detector", kind: "detector", component: "detector:test" },
    { id: "policy", kind: "policy", component: "policy.quantile" },
    { id: "output", kind: "output", component: "output.evidence" },
  ],
  edges: [
    { source: "input", target: "detector" },
    { source: "detector", target: "policy" },
    { source: "policy", target: "output" },
  ],
});
const catalog = normalizeCatalog({
  catalog_id: "catalog",
  authoring_enabled: true,
  templates: [],
  components: [
    {
      id: "source.aligned",
      kind: "source",
      label: "Inputs",
      description: "Aligned values",
      strategies: ["adaptive_stream"],
      input_type: null,
      output_type: "features",
    },
    {
      id: "detector:test",
      kind: "detector",
      label: "Detector",
      description: "Scores",
      strategies: ["adaptive_stream"],
      input_type: "features",
      output_type: "scores",
    },
    {
      id: "policy.quantile",
      kind: "policy",
      label: "Threshold",
      description: "Threshold",
      strategies: ["adaptive_stream"],
      input_type: "scores",
      output_type: "decisions",
    },
    {
      id: "output.evidence",
      kind: "output",
      label: "Evidence",
      description: "Evidence",
      strategies: ["adaptive_stream"],
      input_type: "decisions",
      output_type: "evidence",
    },
  ],
});
const pipeline = () =>
  normalizeView({
    id: "design",
    name: "Room pipeline",
    description: "",
    archived: false,
    version: 1,
    draft: definition,
    layout: normalizeLayout(),
    revisions: [
      {
        id: "revision",
        pipeline_id: "design",
        number: 1,
        definition,
        fingerprint: "hash",
        catalog_id: "catalog",
        created_at: "2026-10-16T12:00:00Z",
      },
    ],
    created_at: "2026-10-16T12:00:00Z",
    updated_at: "2026-10-16T12:00:00Z",
  });
const props = () => ({
  id: "design",
  catalog,
  canEdit: true,
  targets: [],
  services: [],
  byStream: new Map<string, Set<string>>(),
  collectionReady: true,
  onBack: vi.fn(),
  onOpen: vi.fn(),
  onRevision: vi.fn(),
  onOperation: vi.fn(),
  onStarted: vi.fn(),
});

beforeEach(() => {
  vi.clearAllMocks();
  clearNavigationDrafts();
  vi.mocked(pipelinesApi.get).mockResolvedValue(pipeline());
});
afterEach(cleanup);

describe("saved graphical pipeline editor", () => {
  it("keeps immutable revision controls read only", async () => {
    render(<PipelineEditor {...props()} revisionId="revision" />);
    await screen.findByText("Immutable revision 1", { exact: false });
    expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Publish revision" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Start revision" })).toBeTruthy();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Selected component" }),
      { target: { value: "input" } },
    );
    expect(
      (screen.getByRole("textbox", { name: "Node title" }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
  });

  it("preserves the local draft after a concurrency conflict and saves a separate copy", async () => {
    vi.mocked(pipelinesApi.save).mockRejectedValue(
      new ApiRequestError("The shared draft changed", 409),
    );
    vi.mocked(pipelinesApi.create).mockResolvedValue({
      ...pipeline(),
      id: "copy",
    });
    const callbacks = props();
    render(<PipelineEditor {...callbacks} />);
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Selected component" }),
      { target: { value: "input" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Node title" }), {
      target: { value: "My source label" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByRole("region", { name: "Draft conflict" });
    expect(
      (screen.getByRole("textbox", { name: "Node title" }) as HTMLInputElement)
        .value,
    ).toBe("My source label");
    fireEvent.click(
      screen.getByRole("button", { name: "Save as a new design" }),
    );
    await waitFor(() => expect(callbacks.onOpen).toHaveBeenCalledWith("copy"));
    expect(pipelinesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Room pipeline (copy)",
        layout: expect.objectContaining({
          nodes: expect.objectContaining({
            input: expect.objectContaining({ label: "My source label" }),
          }),
        }),
      }),
    );
  });

  it("publishes only after real validation accepts the draft", async () => {
    vi.mocked(pipelinesApi.validate).mockResolvedValue({
      valid: false,
      definition,
      issues: [
        {
          code: "input_count",
          message: "Connect all inputs",
          node_id: "detector",
        },
      ],
      features: {},
    });
    render(<PipelineEditor {...props()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Publish revision" }),
    );
    await screen.findByText(
      "Resolve graph validation errors before publishing.",
    );
    expect(pipelinesApi.publish).not.toHaveBeenCalled();
    expect(pipelinesApi.save).not.toHaveBeenCalled();
  });

  it("does not expose an editable draft for an unknown revision link", async () => {
    render(<PipelineEditor {...props()} revisionId="missing" />);
    await screen.findByText(/Published revision not found/);
    expect(
      screen.queryByRole("button", { name: "Publish revision" }),
    ).toBeNull();
  });

  it("retains an unsaved draft across a setup detour", async () => {
    const callbacks = props();
    const first = render(<PipelineEditor {...callbacks} />);
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Selected component" }),
      { target: { value: "input" } },
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Node title" }), {
      target: { value: "Saved during navigation" },
    });
    first.unmount();
    render(<PipelineEditor {...callbacks} />);
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Selected component" }),
      { target: { value: "input" } },
    );
    expect(
      (screen.getByRole("textbox", { name: "Node title" }) as HTMLInputElement)
        .value,
    ).toBe("Saved during navigation");
    expect(pipelinesApi.save).not.toHaveBeenCalled();
  });

  it("changes detectors using catalog defaults while retaining connections", async () => {
    const nextCatalog = {
      ...catalog,
      components: [
        ...catalog.components,
        {
          ...catalog.components[1]!,
          id: "detector:another",
          label: "Another detector",
          fields: [
            {
              name: "window_size",
              label: "Window size",
              type: "integer" as const,
              default: 20,
            },
          ],
        },
      ],
    };
    const initial = pipeline();
    vi.mocked(pipelinesApi.save).mockImplementation(async (_id, request) =>
      normalizeView({
        ...initial,
        version: 2,
        draft: request.definition,
        layout: request.layout ?? initial.layout,
      }),
    );
    render(<PipelineEditor {...props()} catalog={nextCatalog} />);
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Selected component" }),
      { target: { value: "detector" } },
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Detector model" }), {
      target: { value: "detector:another" },
    });
    expect(
      (
        screen.getByRole("spinbutton", {
          name: "Window size",
        }) as HTMLInputElement
      ).value,
    ).toBe("20");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved.");
    expect(
      vi.mocked(pipelinesApi.save).mock.calls[0]?.[1].definition.edges,
    ).toEqual(initial.draft.edges);
    expect(
      vi
        .mocked(pipelinesApi.save)
        .mock.calls[0]?.[1].definition.nodes?.find(
          (node) => node.id === "detector",
        ),
    ).toMatchObject({
      component: "detector:another",
      params: { window_size: 20 },
    });
  });

  it("offers canonical upstream feature names after projection instead of raw slot guesses", async () => {
    const draft = normalizeDefinition({
      ...definition,
      nodes: [
        ...definition.nodes,
        {
          id: "projection",
          kind: "transform",
          component: "adaptive.uncentered_pca",
          params: {},
        },
        {
          id: "selection",
          kind: "transform",
          component: "features.select",
          params: { features: [] },
        },
      ],
      edges: [
        { source: "input", target: "projection" },
        { source: "projection", target: "selection" },
        { source: "selection", target: "detector" },
        ...definition.edges.filter((edge) => edge.source !== "input"),
      ],
    });
    vi.mocked(pipelinesApi.get).mockResolvedValue({ ...pipeline(), draft });
    vi.mocked(pipelinesApi.validate).mockResolvedValue({
      valid: false,
      definition: draft,
      issues: [],
      features: {
        projection: [{ name: "projection_component_1", slots: ["value"] }],
      },
    });
    const components = [
      ...catalog.components,
      {
        ...catalog.components[0]!,
        id: "features.select",
        kind: "transform" as const,
        fields: [
          { name: "features", label: "Features", type: "features" as const },
        ],
      },
    ];
    render(
      <PipelineEditor {...props()} catalog={{ ...catalog, components }} />,
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Selected component" }),
      { target: { value: "selection" } },
    );
    expect(
      screen.queryByRole("checkbox", { name: "Value · value" }),
    ).toBeNull();
    expect(
      await screen.findByRole(
        "checkbox",
        { name: "projection_component_1" },
        { timeout: 2500 },
      ),
    ).toBeTruthy();
  });
});
