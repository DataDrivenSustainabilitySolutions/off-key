import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import Account from "@/features/account/AccountSettings";
import Registration from "@/pages/Registration";

const everything = ["manage_sources", "manage_monitors", "manage_alarms", "manage_members"];
const { auth, getMembers, inviteMember, updateMember, removeMember, getRoles, getPermissions, createRole, updateRole, deleteRole, post } = vi.hoisted(() => {
  const auth = {
    member: { id: 1, email: "admin@example.com", role: "admin", permissions: [] as string[] },
    can: (permission: string) => auth.member.permissions.includes(permission),
    logout: vi.fn(), retryAuthentication: vi.fn(),
  };
  return {
    auth, getMembers: vi.fn(), inviteMember: vi.fn(), updateMember: vi.fn(), removeMember: vi.fn(), post: vi.fn(),
    getRoles: vi.fn(), getPermissions: vi.fn(), createRole: vi.fn(), updateRole: vi.fn(), deleteRole: vi.fn(),
  };
});

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/components/AuthLayout", () => ({
  AuthLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AUTH_LINK_CLASS: "", AUTH_ERROR_CLASS: "", AUTH_SUBMIT_BUTTON_CLASS: "",
}));
vi.mock("@/lib/member-api", () => ({ getMembers, inviteMember, updateMember, removeMember, getRoles, getPermissions, createRole, updateRole, deleteRole }));
vi.mock("@/lib/api-client", () => ({ apiUtils: { post } }));

const member = { id: 2, email: "member@example.com", role: "user", is_active: true, is_verified: true };
const roles = [
  { id: "admin", name: "Administrator", permissions: everything, editable: false, built_in: true, members: 1 },
  { id: "user", name: "Member", permissions: [], editable: true, built_in: true, members: 1 },
  { id: "operator", name: "Operator", permissions: ["manage_monitors"], editable: true, built_in: false, members: 0 },
];
beforeEach(() => {
  auth.member = { id: 1, email: "admin@example.com", role: "admin", permissions: everything };
  auth.retryAuthentication.mockClear();
  getRoles.mockResolvedValue(roles);
  getPermissions.mockResolvedValue(everything.map((id) => ({ id, description: `Allows ${id}.` })));
  createRole.mockImplementation(async (name: string, permissions: string[]) => ({ id: "auditor", name, permissions, editable: true, built_in: false, members: 0 }));
  updateRole.mockImplementation(async (id: string, changes: object) => ({ ...roles.find((role) => role.id === id), ...changes }));
  deleteRole.mockResolvedValue(undefined);
  getMembers.mockResolvedValue([{ ...member, id: 1, email: auth.member.email, role: "admin" }, member]);
  inviteMember.mockResolvedValue({ message: "Invitation sent." });
  updateMember.mockResolvedValue(member);
  removeMember.mockResolvedValue(undefined);
  post.mockResolvedValue({ message: "Accepted" });
});

it("shows member access without offering member management", async () => {
  auth.member = { id: 1, email: "admin@example.com", role: "operator", permissions: ["manage_monitors"] };
  render(<MemoryRouter><Account /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "Send invitation" })).toBeNull();
  expect(getMembers).not.toHaveBeenCalled();
  const signedIn = screen.getByRole("region", { name: "Signed in" });
  expect(within(signedIn).getByText("admin@example.com")).toBeTruthy();
  expect(await within(signedIn).findByText("Operator")).toBeTruthy();
  expect(signedIn.textContent).toContain("Your role: view organization data, manage monitors.");
  expect(screen.queryByRole("heading", { name: "Members" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Roles" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Invite member" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
});

it("invites colleagues and updates their role", async () => {
  render(<MemoryRouter><Account /></MemoryRouter>);
  await screen.findByText(member.email);
  // The member list comes first; the invitation form opens on request.
  expect(screen.queryByLabelText("Email")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Invite member" }));
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "colleague@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
  await waitFor(() => expect(inviteMember).toHaveBeenCalledWith("colleague@example.com", "user"));
  await screen.findByRole("status");
  expect(screen.queryByRole("form", { name: "Invite member" })).toBeNull();
  await within(screen.getByLabelText("Role for member@example.com")).findByRole("option", { name: "Operator" });
  fireEvent.change(screen.getByLabelText("Role for member@example.com"), { target: { value: "operator" } });
  await waitFor(() => expect(updateMember).toHaveBeenCalledWith(member, { role: "operator" }));
  expect((screen.getByLabelText("Role for admin@example.com") as HTMLSelectElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
});

it("disables a member after confirmation and reports API failures", async () => {
  updateMember.mockRejectedValue(new Error("Keep at least one active member who can manage members"));
  render(<MemoryRouter><Account /></MemoryRouter>);
  await screen.findByText(member.email);
  const enabled = screen.getAllByRole("button", { name: "Disable" }).find((button) => !(button as HTMLButtonElement).disabled);
  fireEvent.click(enabled!);
  const dialog = await screen.findByRole("dialog", { name: "Disable access?" });
  expect(dialog.textContent).toContain(member.email);
  expect(updateMember).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Disable access" }));
  await waitFor(() => expect(updateMember).toHaveBeenCalledWith(member, { is_active: false }));
  expect((await screen.findByRole("alert")).textContent).toContain("Keep at least one active member who can manage members");
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

it("creates a role from chosen permissions", async () => {
  render(<MemoryRouter><Account /></MemoryRouter>);
  const group = await screen.findByRole("region", { name: "Roles" });
  const list = await within(group).findByRole("list", { name: "Roles" });
  expect(within(list).getByText("All permissions")).toBeTruthy();
  expect(within(list).getByText("View only")).toBeTruthy();
  fireEvent.click(within(group).getByRole("button", { name: "New role" }));
  const form = within(screen.getByRole("dialog", { name: "New role" })).getByRole("form", { name: "New role" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Auditor" } });
  fireEvent.click(await within(form).findByRole("checkbox", { name: /Manage alarms/ }));
  fireEvent.click(within(form).getByRole("button", { name: "Create role" }));
  await waitFor(() => expect(createRole).toHaveBeenCalledWith("Auditor", ["manage_alarms"]));
  expect((await within(group).findByRole("status")).textContent).toContain("Auditor created.");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(auth.retryAuthentication).not.toHaveBeenCalled();
});

it("edits a role's permissions and refreshes your own access when it is your role", async () => {
  auth.member = { id: 1, email: "admin@example.com", role: "user", permissions: ["manage_members"] };
  render(<MemoryRouter><Account /></MemoryRouter>);
  const group = await screen.findByRole("region", { name: "Roles" });
  const [administrator, memberRole] = await within(group).findAllByRole("listitem");
  // Administrator cannot be edited; built-in roles cannot be deleted.
  expect(within(administrator!).queryByRole("button", { name: "Edit Administrator" })).toBeNull();
  expect(within(memberRole!).queryByRole("button", { name: "Delete Member" })).toBeNull();
  fireEvent.click(within(memberRole!).getByRole("button", { name: "Edit Member" }));
  const form = within(screen.getByRole("dialog", { name: "Edit role" })).getByRole("form", { name: "Edit Member" });
  fireEvent.click(await within(form).findByRole("checkbox", { name: /Manage sources/ }));
  fireEvent.click(within(form).getByRole("button", { name: "Save role" }));
  await waitFor(() => expect(updateRole).toHaveBeenCalledWith("user", { name: "Member", permissions: ["manage_sources"] }));
  await waitFor(() => expect(auth.retryAuthentication).toHaveBeenCalledOnce());
});

it("deletes a role nobody holds after confirmation", async () => {
  render(<MemoryRouter><Account /></MemoryRouter>);
  const group = await screen.findByRole("region", { name: "Roles" });
  const operator = (await within(group).findByText("Operator")).closest("li")!;
  fireEvent.click(within(operator).getByRole("button", { name: "Delete Operator" }));
  const dialog = await screen.findByRole("dialog", { name: "Delete Operator?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete role" }));
  await waitFor(() => expect(deleteRole).toHaveBeenCalledWith("operator"));
  expect((await within(group).findByRole("status")).textContent).toContain("Operator deleted.");
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
