import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import Account from "@/pages/Account";
import Registration from "@/pages/Registration";

const { auth, getMembers, inviteMember, updateMember, removeMember, post } = vi.hoisted(() => ({
  auth: { isAdmin: true, member: { id: 1, email: "admin@example.com" } },
  getMembers: vi.fn(), inviteMember: vi.fn(), updateMember: vi.fn(), removeMember: vi.fn(), post: vi.fn(),
}));

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/components/NavigationBar", () => ({ NavigationBar: () => null }));
vi.mock("@/components/AuthLayout", () => ({
  AuthLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AUTH_LINK_CLASS: "", AUTH_ERROR_CLASS: "", AUTH_SUBMIT_BUTTON_CLASS: "",
}));
vi.mock("@/lib/member-api", () => ({ getMembers, inviteMember, updateMember, removeMember }));
vi.mock("@/lib/api-client", () => ({ apiUtils: { post } }));

const member = { id: 2, email: "member@example.com", role: "user", is_active: true, is_verified: true };
beforeEach(() => {
  vi.clearAllMocks();
  auth.isAdmin = true;
  getMembers.mockResolvedValue([{ ...member, id: 1, email: auth.member.email, role: "admin" }, member]);
  inviteMember.mockResolvedValue({ message: "Invitation sent." });
  updateMember.mockResolvedValue(member);
  removeMember.mockResolvedValue(undefined);
  post.mockResolvedValue({ message: "Accepted" });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("shows member access without offering administrator controls", async () => {
  auth.isAdmin = false;
  render(<MemoryRouter><Account /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "Send invitation" })).toBeNull();
  expect(getMembers).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Account" }).tagName).toBe("H1");
  expect(screen.getByRole("heading", { name: "Your access" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "About Your access" }));
  expect((await screen.findByRole("tooltip")).textContent).toContain("Members can view all organization data");
});

it("invites colleagues and updates their role", async () => {
  render(<MemoryRouter><Account /></MemoryRouter>);
  await screen.findByText(member.email);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "colleague@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
  await waitFor(() => expect(inviteMember).toHaveBeenCalledWith("colleague@example.com", "user"));
  await screen.findByRole("status");
  fireEvent.change(screen.getByLabelText("Role for member@example.com"), { target: { value: "admin" } });
  await waitFor(() => expect(updateMember).toHaveBeenCalledWith(member, { role: "admin" }));
  expect((screen.getByLabelText("Role for admin@example.com") as HTMLSelectElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
});

it("disables a member after confirmation and reports API failures", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  updateMember.mockRejectedValue(new Error("Keep at least one active administrator"));
  render(<MemoryRouter><Account /></MemoryRouter>);
  await screen.findByText(member.email);
  const enabled = screen.getAllByRole("button", { name: "Disable" }).find((button) => !(button as HTMLButtonElement).disabled);
  fireEvent.click(enabled!);
  await waitFor(() => expect(updateMember).toHaveBeenCalledWith(member, { is_active: false }));
  expect((await screen.findByRole("alert")).textContent).toContain("Keep at least one active administrator");
});

it("offers removal only after disabling, and cancellation preserves the member", async () => {
  getMembers.mockResolvedValue([{ ...member, is_active: false }]);
  render(<MemoryRouter><Account /></MemoryRouter>);
  const remove = await screen.findByRole("button", { name: "Remove" });
  remove.focus();
  fireEvent.click(remove);
  const dialog = screen.getByRole("dialog", { name: "Remove member?" });
  expect(dialog.textContent).toContain(member.email);
  expect(dialog.textContent).toContain("new invitation");
  expect(dialog.textContent).toContain("Shared catalogue data");
  expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(removeMember).not.toHaveBeenCalled();
  expect(screen.getByText(member.email)).toBeTruthy();
  await waitFor(() => expect(document.activeElement).toBe(remove));
});

it("removes the disabled member only after the server succeeds and keeps the list focused", async () => {
  getMembers.mockResolvedValue([{ ...member, is_active: false }]);
  let complete!: () => void;
  removeMember.mockReturnValue(new Promise<void>((resolve) => { complete = resolve; }));
  render(<MemoryRouter><Account /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove member" }));
  expect(removeMember).toHaveBeenCalledExactlyOnceWith(member.id);
  const dialog = screen.getByRole("dialog");
  expect((within(dialog).getByRole("button", { name: "Removing…" }) as HTMLButtonElement).disabled).toBe(true);
  expect((within(dialog).getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
  expect(within(screen.getByRole("list", { name: "Members", hidden: true })).getByText(member.email)).toBeTruthy();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.getByRole("dialog")).toBeTruthy();
  await act(async () => complete());
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByRole("status").textContent).toContain(`${member.email} has been removed`);
  expect(within(screen.getByRole("list", { name: "Members" })).queryByText(member.email)).toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("list", { name: "Members" })));
});

it("keeps failed removal visible and allows a retry", async () => {
  getMembers.mockResolvedValue([{ ...member, is_active: false }]);
  removeMember.mockRejectedValueOnce(new Error("Disable this member before removing them"));
  render(<MemoryRouter><Account /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove member" }));
  const dialog = screen.getByRole("dialog");
  expect((await within(dialog).findByRole("alert")).textContent).toContain("Disable this member");
  expect(within(screen.getByRole("list", { name: "Members", hidden: true })).getByText(member.email)).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Remove member" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(removeMember).toHaveBeenCalledTimes(2);
});

it("requires an invitation link before offering account creation", () => {
  render(<MemoryRouter initialEntries={["/register"]}><Registration /></MemoryRouter>);
  expect(screen.queryByLabelText("Password")).toBeNull();
  expect(screen.getByText(/Ask your administrator/)).toBeTruthy();
});

it("accepts the invitation with matching passwords and no client-selected identity", async () => {
  const token = "t".repeat(43);
  render(<MemoryRouter initialEntries={[`/register#token=${token}`]}><Registration /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse battery staple" } });
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different" } });
  fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
  expect(post).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "correct horse battery staple" } });
  fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/v1/auth/accept-invitation", { token, password: "correct horse battery staple" }));
  expect((await screen.findByRole("status")).textContent).toContain("Your account is ready");
});
