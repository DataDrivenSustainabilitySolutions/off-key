import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InlineName } from "@/features/catalogue/InlineName";

afterEach(cleanup);

const edit = () => {
  fireEvent.click(screen.getByRole("button", { name: "Rename title" }));
  return screen.getByRole("textbox", {
    name: "Rename title",
  }) as HTMLInputElement;
};

describe("inline persisted names", () => {
  it("focuses and selects the current name, then Escape restores the title without saving", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe("Garage".length);
    fireEvent.change(input, { target: { value: "Attempted name" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(screen.queryByRole("textbox")).toBeNull();
    const title = screen.getByRole("button", { name: "Rename title" });
    expect(title.textContent).toBe("Garage");
    expect(document.activeElement).toBe(title);
    expect(save).not.toHaveBeenCalled();
  });

  it("trims a valid name and saves once when Enter is followed by blur", async () => {
    let resolve: () => void = () => undefined;
    const save = vi.fn(
      () =>
        new Promise<void>((done) => {
          resolve = done;
        }),
    );
    const { rerender } = render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    fireEvent.change(input, { target: { value: "  North garage  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(save).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledWith("North garage");
    expect(input.disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Saving…");
    await act(async () => {
      rerender(<InlineName value="North garage" onSave={save} />);
      resolve();
    });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("button").textContent).toBe("North garage");
    expect(screen.queryByRole("status")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button"));
  });

  it("commits an edited name on blur", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    fireEvent.change(input, { target: { value: "Yard" } });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(save).toHaveBeenCalledWith("Yard");
  });

  it("keeps a failed attempt editable for retry instead of presenting it as saved", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("private server detail"))
      .mockResolvedValueOnce(undefined);
    const { rerender } = render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    fireEvent.change(input, { target: { value: "Yard" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(input.value).toBe("Yard");
    expect(input.disabled).toBe(false);
    expect(screen.getByRole("alert").textContent).not.toContain(
      "private server detail",
    );
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(save).toHaveBeenCalledTimes(2);
    rerender(<InlineName value="Yard" onSave={save} />);
    expect(screen.getByRole("button").textContent).toBe("Yard");
  });

  it("rejects blank names and does not persist unchanged whitespace-only edits", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toBe("Enter a name.");
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: " Garage " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(save).not.toHaveBeenCalled();
  });

  it("leaves names read-only when permission is unavailable", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <InlineName
        value="Garage"
        onSave={save}
        editable={false}
        disabledReason="Sign in as an editor to rename."
      />,
    );
    const title = screen.getByRole("button", {
      name: "Rename title",
    }) as HTMLButtonElement;
    expect(title.disabled).toBe(true);
    fireEvent.click(title);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(title.textContent).toBe("Garage");
    expect(screen.getByText("Sign in as an editor to rename.")).toBeTruthy();
    expect(save).not.toHaveBeenCalled();
  });

  it("shows a refreshed canonical name beside a failed concurrent edit", async () => {
    const save = vi.fn().mockRejectedValue(new Error("Conflict"));
    const { rerender } = render(<InlineName value="Garage" onSave={save} />);
    const input = edit();
    fireEvent.change(input, { target: { value: "My name" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByRole("alert");
    rerender(
      <InlineName
        value="Other editor's name"
        onSave={save}
        saveError="The catalog changed. Review the current name before trying again."
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "The catalog changed.",
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "Current saved name: Other editor's name",
    );
    expect(input.value).toBe("My name");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("button").textContent).toBe("Other editor's name");
    expect(save).toHaveBeenCalledOnce();
  });

  it("keeps local validation visible when an earlier save had an error", () => {
    const save = vi.fn();
    render(
      <InlineName
        value="Garage"
        onSave={save}
        saveError="Earlier database conflict"
      />,
    );
    const input = edit();
    fireEvent.change(input, { target: { value: "  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toBe("Enter a name.");
    expect(save).not.toHaveBeenCalled();
  });
});
