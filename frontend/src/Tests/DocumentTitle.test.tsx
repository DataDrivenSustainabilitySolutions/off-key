import { StrictMode } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useDetailDocumentTitle, useDocumentTitle, useOverlayDocumentTitle } from "@/hooks/use-document-title";

function Detail({ name }: { name: string }) {
  useDetailDocumentTitle(name, "Monitoring");
  return null;
}

function Workspace({ scope, detail, settings }: { scope?: string; detail?: string; settings?: string }) {
  useDocumentTitle(scope, "Monitoring");
  useOverlayDocumentTitle(settings);
  return detail ? <Detail name={detail} /> : null;
}

describe("browser title ownership", () => {
  it("keeps a detail title through parent updates and restores the current scope when it closes", () => {
    const view = render(<StrictMode><Workspace scope="Roof" detail="Room climate" /></StrictMode>);
    expect(document.title).toBe("Room climate · Monitoring · Aberration");
    view.rerender(<StrictMode><Workspace scope="Workshop" detail="Room climate" /></StrictMode>);
    expect(document.title).toBe("Room climate · Monitoring · Aberration");
    view.rerender(<StrictMode><Workspace scope="Workshop" /></StrictMode>);
    expect(document.title).toBe("Workshop · Monitoring · Aberration");
    view.unmount();
    expect(document.title).toBe("Aberration");
  });

  it("restores a renamed detail after settings close and releases it when the page leaves", () => {
    const view = render(<Workspace detail="Room climate" settings="Appearance" />);
    expect(document.title).toBe("Appearance · Aberration");
    view.rerender(<Workspace detail="Workshop climate" settings="Account settings" />);
    expect(document.title).toBe("Account settings · Aberration");
    view.rerender(<Workspace detail="Workshop climate" />);
    expect(document.title).toBe("Workshop climate · Monitoring · Aberration");
    view.unmount();
    expect(document.title).toBe("Aberration");
  });
});
