import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HelpTooltip } from "@/components/HelpTooltip";

describe("contextual help", () => {
  it("opens on keyboard focus or click and closes with Escape", async () => {
    render(<HelpTooltip label="Retention">Cleanup runs periodically.</HelpTooltip>);
    const trigger = screen.getByRole("button", { name: "About Retention" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.focus(trigger);
    expect((await screen.findByRole("tooltip")).textContent).toBe("Cleanup runs periodically.");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());

    fireEvent.click(trigger);
    expect((await screen.findByRole("tooltip")).textContent).toBe("Cleanup runs periodically.");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });
});
