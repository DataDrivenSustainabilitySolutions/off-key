import { useState, type CSSProperties } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorerSidebarResize } from "@/features/explorer/ExplorerSidebarResize";

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("innerWidth", 1440);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => window.setTimeout(callback, 16));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    pointerId: number;
    isPrimary: boolean;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init); this.pointerId = init.pointerId ?? 1; this.isPrimary = init.isPrimary ?? true;
    }
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return new DOMRect(0, 0, Number.parseFloat(this.closest<HTMLElement>(".ex-shell")?.style.getPropertyValue("--ex-sidebar-width") ?? "288"), 900);
  });
});

function mount() {
  const committed = vi.fn();
  function Dock() {
    const [width, setWidth] = useState(288);
    return <div className="ex-shell" style={{ "--ex-sidebar-width": `${width}px` } as CSSProperties}>
      <div className="ex-sidebar-dock"><ExplorerSidebarResize width={width} onCommit={(next) => { committed(next); setWidth(next); }} /></div>
    </div>;
  }
  const view = render(<Dock />);
  const edge = screen.getByRole("separator", { name: "Resize explorer sidebar" });
  edge.setPointerCapture = vi.fn(); edge.hasPointerCapture = vi.fn(() => true); edge.releasePointerCapture = vi.fn();
  const shell = edge.closest<HTMLElement>(".ex-shell")!;
  const pointer = { pointerId: 1, isPrimary: true, button: 0 };
  return { ...view, edge, shell, committed, pointer };
}

describe("desktop sidebar resize", () => {
  it("captures a drag outside the edge and commits once on release, including the final pointer position", () => {
    const { edge, shell, committed, pointer } = mount();
    fireEvent.pointerDown(edge, { ...pointer, clientX: 288 });
    expect(edge.setPointerCapture).toHaveBeenCalledWith(1);
    fireEvent.pointerMove(edge, { ...pointer, clientX: 340 });
    fireEvent.pointerMove(edge, { ...pointer, clientX: 410 });
    expect(committed).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(16));
    expect(edge.getAttribute("aria-valuenow")).toBe("410");
    fireEvent.pointerUp(edge, { ...pointer, clientX: 420 });
    expect(committed).toHaveBeenCalledExactlyOnceWith(420);
    expect(shell.style.getPropertyValue("--ex-sidebar-width")).toBe("420px");
    expect(shell.classList.contains("is-resizing")).toBe(false);
    expect(edge.releasePointerCapture).toHaveBeenCalledWith(1);
    act(() => vi.runAllTimers());
    expect(committed).toHaveBeenCalledOnce();
  });

  it.each(["pointercancel", "escape", "blur"])("restores the previous width after %s without committing", (reason) => {
    const { edge, shell, committed, pointer } = mount();
    fireEvent.pointerDown(edge, { ...pointer, clientX: 288 });
    fireEvent.pointerMove(edge, { ...pointer, clientX: 430 });
    act(() => vi.advanceTimersByTime(16));
    if (reason === "pointercancel") fireEvent.pointerCancel(edge, pointer);
    else if (reason === "escape") fireEvent.keyDown(edge, { key: "Escape" });
    else fireEvent.blur(window);
    expect(shell.style.getPropertyValue("--ex-sidebar-width")).toBe("288px");
    expect(shell.classList.contains("is-resizing")).toBe(false);
    expect(committed).not.toHaveBeenCalled();
  });

  it("ignores unrelated pointers and respects the available space for the workspace", () => {
    const { edge, shell, committed, pointer } = mount();
    vi.stubGlobal("innerWidth", 820);
    act(() => window.dispatchEvent(new Event("resize")));
    expect(edge.getAttribute("aria-valuemax")).toBe("340");
    fireEvent.pointerDown(edge, { ...pointer, clientX: 288 });
    fireEvent.pointerMove(edge, { ...pointer, pointerId: 2, clientX: 900 });
    fireEvent.pointerUp(edge, { ...pointer, pointerId: 2, clientX: 900 });
    expect(committed).not.toHaveBeenCalled();
    fireEvent.pointerMove(edge, { ...pointer, clientX: 900 });
    fireEvent.pointerUp(edge, { ...pointer, clientX: 900 });
    expect(committed).toHaveBeenCalledExactlyOnceWith(340);
    expect(shell.style.getPropertyValue("--ex-sidebar-width")).toBe("340px");
  });

  it("supports keyboard sizing, bounds, and double-click reset", () => {
    const { edge, committed } = mount();
    fireEvent.keyDown(edge, { key: "ArrowRight", shiftKey: true });
    expect(edge.getAttribute("aria-valuenow")).toBe("352");
    fireEvent.keyDown(edge, { key: "ArrowLeft" });
    expect(edge.getAttribute("aria-valuenow")).toBe("336");
    fireEvent.keyDown(edge, { key: "Home" });
    expect(edge.getAttribute("aria-valuenow")).toBe("240");
    fireEvent.keyDown(edge, { key: "End" });
    expect(edge.getAttribute("aria-valuenow")).toBe("480");
    fireEvent.doubleClick(edge);
    expect(committed).toHaveBeenLastCalledWith(288);
    expect(edge.getAttribute("aria-valuenow")).toBe("288");
  });

  it("releases pointer capture and pending animation work when the desktop sidebar unmounts", () => {
    const { edge, shell, unmount, committed, pointer } = mount();
    fireEvent.pointerDown(edge, { ...pointer, clientX: 288 });
    fireEvent.pointerMove(edge, { ...pointer, clientX: 420 });
    unmount();
    act(() => vi.runAllTimers());
    expect(shell.style.getPropertyValue("--ex-sidebar-width")).toBe("288px");
    expect(edge.releasePointerCapture).toHaveBeenCalledWith(1);
    expect(committed).not.toHaveBeenCalled();
  });
});
