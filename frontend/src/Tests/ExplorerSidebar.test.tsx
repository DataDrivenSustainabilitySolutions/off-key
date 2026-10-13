import { act, cleanup, fireEvent, render as renderUI, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorerSidebar } from "@/features/explorer/ExplorerSidebar";
import { ExplorerList, type ExplorerRow, type ListPosition } from "@/features/explorer/ExplorerList";
import { buildNavigationIndex, navigationRows } from "@/features/explorer/navigationIndex";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import type { SystemDocument } from "@/features/catalogue/systemTypes";
import { apiClient } from "@/lib/api-client";

const viewportHeight = 360;
const rowHeight = 72;
const initialScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const initialWindowObserver = Object.getOwnPropertyDescriptor(window, "ResizeObserver");

function render(element: ReactNode, path = "/") {
  return renderUI(element, { wrapper: ({ children }) => <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter> });
}

beforeEach(() => {
  // Exercise the real TanStack virtualizer. jsdom provides no element geometry,
  // so supply only the browser measurements and scrolling behaviour it observes.
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll") ? viewportHeight : this.tagName === "LI" ? rowHeight : 24;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(264);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll") ? viewportHeight : 24;
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll")
      ? Number.parseFloat(this.querySelector<HTMLElement>(".ex-list")?.style.height ?? "0")
      : 24;
  });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: function (this: HTMLElement, options: ScrollToOptions) {
      const next = options.top ?? 0;
      if (this.scrollTop === next) return;
      this.scrollTop = next;
      this.dispatchEvent(new Event("scroll"));
    },
  });
  class ViewportObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, "ResizeObserver", { configurable: true, value: ViewportObserver });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (initialScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", initialScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  if (initialWindowObserver) Object.defineProperty(window, "ResizeObserver", initialWindowObserver);
  else Reflect.deleteProperty(window, "ResizeObserver");
});

function system(readings = 3): SystemDocument {
  return {
    ...createEmptySystem("Test catalogue"),
    connections: [{ id: "broker", label: "North laboratory", protocol: "mqtt", host: "private.example.invalid", port: 1883, transport: "tcp", tls: false }],
    streams: Array.from({ length: readings }, (_, position) => ({
      id: `value-${position}`, label: `Value ${position}`, connection_id: "broker", topic: `site/room/value${position}`,
      value_type: "number", category: "Environment",
    })),
    groups: [{ id: "catalogue-watch", label: "Building A", member_ids: ["broker"] }],
  };
}

function sidebarOptions(document = system()) {
  const index = buildNavigationIndex(document);
  return {
    index, scopeKey: index.rootKey, rows: navigationRows(index, index.rootKey), title: "Test catalogue",
    catalogueGroups: document.groups, query: "", selectedKey: null,
    positions: new Map<string, ListPosition>(), loading: false,
    onQuery: vi.fn(), onScope: vi.fn(), onOpen: vi.fn(), onBack: vi.fn(), onInspect: vi.fn(),
    onSettings: vi.fn(), onWorkspace: vi.fn(), onDismiss: vi.fn(),
  };
}

function listOptions(document = system()) {
  const index = buildNavigationIndex(document);
  const broker = index.nodes.get(index.objectKeys.get("broker")![0]!)!;
  const branch = navigationRows(index, broker.key)[0]!.node;
  return {
    rows: navigationRows(index, branch.key), viewKey: branch.key,
    positions: new Map<string, ListPosition>(), selectedKey: null,
    onOpen: vi.fn(), onBack: vi.fn(),
  };
}

describe("explorer sidebar and catalogue list", () => {
  it.each(["/", "/sources?broker=broker"])("links both primary workspaces and identifies the current one at %s", path => {
    render(<ExplorerSidebar {...sidebarOptions()} />, path);
    const workspaces = within(screen.getByRole("group", { name: "Workspaces" }));
    const monitoring = workspaces.getByRole("link", { name: "Monitoring" });
    const sources = workspaces.getByRole("link", { name: "Data sources" });
    expect(monitoring.getAttribute("href")).toBe("/");
    expect(sources.getAttribute("href")).toBe("/sources");
    expect(monitoring.getAttribute("aria-current")).toBe(path === "/" ? "page" : null);
    expect(sources.getAttribute("aria-current")).toBe(path === "/" ? null : "page");
  });

  it("preserves normal link behavior when opening Monitoring in another tab", () => {
    const options = sidebarOptions();
    render(<ExplorerSidebar {...options} />);
    fireEvent.click(screen.getByRole("link", { name: "Monitoring" }), { ctrlKey: true });
    expect(options.onWorkspace).not.toHaveBeenCalled();
  });

  it("counts brokers independently of the unassigned entity branch", () => {
    const document = system();
    document.devices.push({ id: "loose", label: "Unassigned sensor", kind: "sensor" });
    const options = sidebarOptions(document);
    render(<ExplorerSidebar {...options} />);
    expect(screen.getByText("1 broker · unassigned entities")).toBeTruthy();
    expect(screen.queryByText("2 brokers")).toBeNull();
  });

  it("moves from search into the rendered virtual window after scrolling past the first row", () => {
    const document = system(4000);
    const list = listOptions(document);
    render(<ExplorerSidebar {...sidebarOptions(document)} rows={list.rows} scopeKey={list.viewKey} />);
    const viewport = screen.getByRole("list").parentElement!;
    fireEvent.scroll(viewport, { target: { scrollTop: 2000 * rowHeight } });
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    const input = screen.getByRole("searchbox", { name: "Search catalogue" });
    act(() => input.focus());
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(window.document.activeElement?.getAttribute("data-row")).not.toBeNull();
    expect(window.document.activeElement).not.toBe(input);
  });

  it("renders a bounded viewport for 4,000 topics and reaches late items without mounting the entire list", () => {
    const options = listOptions(system(4000));
    render(<ExplorerList {...options} />);
    const list = screen.getByRole("list", { name: "Catalogue items" });
    expect(within(list).getAllByRole("button").length).toBeLessThanOrEqual(12);
    expect(screen.getByRole("button", { name: "value0, preview" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "value2000, preview" })).toBeNull();
    const scroll = list.parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 2000 * rowHeight } });
    expect(screen.getByRole("button", { name: "value2000, preview" })).toBeTruthy();
    expect(within(list).getAllByRole("button").length).toBeLessThanOrEqual(18);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(options.positions.get(options.viewKey)?.offset).toBe(2000 * rowHeight);
    fireEvent.click(screen.getByRole("button", { name: "value2000, preview" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(options.rows[2000]!.node);
  });

  it("supports keyboard movement across the virtualized window, opening, and returning to a parent", async () => {
    const options = listOptions(system(4000));
    render(<ExplorerList {...options} />);
    const first = screen.getByRole("button", { name: "value0, preview" });
    act(() => first.focus());
    fireEvent.keyDown(first, { key: "ArrowDown" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value1, preview" })));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(options.onOpen).toHaveBeenLastCalledWith(options.rows[3999]!.node);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(options.onBack).toHaveBeenCalledOnce();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value0, preview" })));
  });

  it("restores each branch's scroll position when entering and returning", async () => {
    const options = listOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const scroll = screen.getByRole("list").parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 100 * rowHeight } });
    expect(screen.getByRole("button", { name: "value100, preview" })).toBeTruthy();
    view.rerender(<ExplorerList {...options} viewKey="other-branch" />);
    await waitFor(() => expect(scroll.scrollTop).toBe(0));
    view.rerender(<ExplorerList {...options} />);
    await waitFor(() => expect(scroll.scrollTop).toBe(100 * rowHeight));
    expect(screen.getByRole("button", { name: "value100, preview" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value100, preview" })));
  });

  it("restores the focused topic as well as its viewport after entering another branch", async () => {
    const options = listOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const scroll = screen.getByRole("list").parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 2000 * rowHeight } });
    const previous = screen.getByRole("button", { name: "value2000, preview" });
    act(() => previous.focus());
    expect(options.positions.get(options.viewKey)?.focused).toBe(options.rows[2000]!.node.key);
    const elsewhere = [{ ...options.rows[0]!, label: "Other branch", node: { ...options.rows[0]!.node, key: "other-topic" } }];
    view.rerender(<ExplorerList {...options} rows={elsewhere} viewKey="other-branch" />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Other branch, preview" })));
    view.rerender(<ExplorerList {...options} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value2000, preview" })));
    expect(scroll.scrollTop).toBe(2000 * rowHeight);
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it("reveals a late search result in its canonical branch instead of restoring an unrelated saved viewport", async () => {
    const options = listOptions(system(4000));
    const late = options.rows[3999]!;
    options.positions.set(options.viewKey, { offset: 100 * rowHeight, focused: options.rows[100]!.node.key });
    const view = render(<ExplorerList {...options} viewKey="search:value3999" rows={[late]} />);
    const result = screen.getByRole("button", { name: "value3999, preview" });
    fireEvent.click(result);
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(late.node);
    view.rerender(<ExplorerList {...options} selectedKey={late.node.key} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    const selected = screen.getByRole("button", { name: "value3999, preview" });
    const scroll = screen.getByRole("list").parentElement!;
    const rowStart = 3999 * rowHeight;
    expect(selected.getAttribute("aria-current")).toBe("true");
    expect(rowStart).toBeGreaterThanOrEqual(scroll.scrollTop);
    expect(rowStart + rowHeight).toBeLessThanOrEqual(scroll.scrollTop + viewportHeight);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it("waits for deferred search rows before revealing the selected topic in its canonical scope", async () => {
    const options = sidebarOptions(system(4000));
    const broker = options.index.nodes.get(options.index.objectKeys.get("broker")![0]!)!;
    const branch = navigationRows(options.index, broker.key)[0]!.node;
    const canonicalRows = navigationRows(options.index, branch.key);
    const late = canonicalRows[3999]!;
    const searchRows = [late];
    options.positions.set(branch.key, { offset: 100 * rowHeight, focused: canonicalRows[100]!.node.key });
    const view = render(<ExplorerSidebar {...options} query="value3999" resultsQuery="value3999" rows={searchRows} />);
    fireEvent.click(screen.getByRole("button", { name: "value3999, preview" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(late.node);

    // The input clears immediately, while useDeferredValue still supplies the
    // previous search result. Its view identity must remain a search identity.
    view.rerender(<ExplorerSidebar {...options} query="" resultsQuery="value3999" rows={searchRows}
      scopeKey={branch.key} title={branch.label} selectedKey={late.node.key} />);
    expect((screen.getByRole("searchbox", { name: "Search catalogue" }) as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("list").classList.contains("is-search")).toBe(true);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });

    view.rerender(<ExplorerSidebar {...options} query="" resultsQuery="" rows={canonicalRows}
      scopeKey={branch.key} title={branch.label} selectedKey={late.node.key} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    const scroll = screen.getByRole("list").parentElement!;
    expect(screen.getByRole("list").classList.contains("is-search")).toBe(false);
    expect(3999 * rowHeight).toBeGreaterThanOrEqual(scroll.scrollTop);
    expect(4000 * rowHeight).toBeLessThanOrEqual(scroll.scrollTop + viewportHeight);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(within(screen.getByRole("list")).getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it("keeps complete long names in relative-path rows and accessible titles", () => {
    const options = listOptions();
    const label = `prefix-visible-${"long-relative-path-".repeat(25)}tail`;
    const rows: ExplorerRow[] = [{ ...options.rows[0]!, label }];
    render(<ExplorerList {...options} rows={rows} selectedKey={rows[0]!.node.key} />);
    const button = screen.getByRole("button", { name: `${label}, preview` });
    expect(button.getAttribute("title")).toBe(label);
    expect(button.querySelector(".ex-row-label")?.textContent).toBe(label);
    expect(button.querySelector(".ex-row-label")?.textContent?.startsWith("prefix-visible-")).toBe(true);
    expect(button.getAttribute("aria-current")).toBe("true");
    expect(screen.queryByText("private.example.invalid")).toBeNull();
  });

  it("opens branches, exposes actual ancestors, and leaves workspace navigation explicit", () => {
    const options = sidebarOptions();
    const root = render(<ExplorerSidebar {...options} />);
    const broker = options.index.nodes.get(options.index.objectKeys.get("broker")![0]!)!;
    fireEvent.click(screen.getByRole("button", { name: "North laboratory, open" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(broker);
    const branch = navigationRows(options.index, broker.key)[0]!.node;
    root.rerender(<ExplorerSidebar {...options} scopeKey={branch.key} title={branch.label} rows={navigationRows(options.index, branch.key)} />);
    fireEvent.click(screen.getByRole("button", { name: "Back one level" }));
    expect(options.onBack).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: branch.label }));
    expect(screen.getByText("Current path")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "North laboratory" }));
    expect(options.onScope).toHaveBeenLastCalledWith(broker.key);
    fireEvent.click(screen.getByRole("link", { name: "Monitoring" }));
    expect(options.onWorkspace).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    expect(options.onSettings).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Close explorer" }));
    expect(options.onDismiss).toHaveBeenCalledOnce();
  });

  it("focuses search with the desktop shortcut and clears a query without closing the explorer", () => {
    const options = sidebarOptions();
    render(<ExplorerSidebar {...options} query="temperature" />);
    const search = screen.getByRole("searchbox", { name: "Search catalogue" }) as HTMLInputElement;
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(document.activeElement).toBe(search);
    expect(search.selectionStart).toBe(0);
    expect(search.selectionEnd).toBe("temperature".length);
    fireEvent.change(search, { target: { value: "power" } });
    expect(options.onQuery).toHaveBeenLastCalledWith("power");
    fireEvent.keyDown(search, { key: "Escape" });
    expect(options.onQuery).toHaveBeenLastCalledWith("");
    expect(options.onDismiss).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close search" }));
    expect(options.onBack).toHaveBeenCalledOnce();
  });

  it("enters search results with ArrowDown and retains input focus while the query changes", () => {
    const options = sidebarOptions();
    const node = options.index.nodes.get(options.index.objectKeys.get("value-0")![0]!)!;
    const rows = [{ node, label: "Air temperature", detail: "North laboratory · site/room" }];
    const view = render(<ExplorerSidebar {...options} query="air" rows={rows} />);
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    act(() => search.focus());
    view.rerender(<ExplorerSidebar {...options} query="temperature" rows={rows} />);
    expect(document.activeElement).toBe(search);
    fireEvent.keyDown(search, { key: "ArrowDown" });
    const result = screen.getByRole("button", { name: "Air temperature, preview" });
    expect(document.activeElement).toBe(result);
    fireEvent.keyDown(result, { key: "ArrowRight" });
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(node);
    view.rerender(<ExplorerSidebar {...options} query="missing" rows={[]} />);
    act(() => search.focus());
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(document.activeElement).toBe(search);
    expect(options.onScope).not.toHaveBeenCalled();
  });

  it("keeps catalogue groups navigable without exposing personal grouping", () => {
    const document = system();
    const original = structuredClone(document);
    const options = sidebarOptions(document);
    const save = vi.spyOn(apiClient, "put");
    const view = render(<ExplorerSidebar {...options} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse catalogue groups" }));
    expect(screen.queryByText("Personal groups")).toBeNull();
    expect(screen.queryByRole("button", { name: "Manage personal groups" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Building A/ }));
    expect(options.onScope).toHaveBeenLastCalledWith("catalogue:catalogue-watch");
    expect(options.onOpen).not.toHaveBeenCalled();
    expect(document).toEqual(original);
    expect(save).not.toHaveBeenCalled();
    view.rerender(<ExplorerSidebar {...options} catalogueGroups={[]} />);
    expect(screen.queryByRole("button", { name: "Browse catalogue groups" })).toBeNull();
  });

  it("keeps loading and empty navigation states accessible", () => {
    const options = sidebarOptions();
    const view = render(<ExplorerSidebar {...options} loading />);
    expect(screen.getByRole("status").textContent).toBe("Loading catalogue…");
    expect(screen.queryByRole("list")).toBeNull();
    view.rerender(<ExplorerSidebar {...options} rows={[]} />);
    expect(screen.getByText("No items here.")).toBeTruthy();
  });
});
