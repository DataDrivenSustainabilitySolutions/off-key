import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import Account from "@/pages/Account";
import Registration from "@/pages/Registration";

const { auth, getMembers, inviteMember, updateMember, post } = vi.hoisted(() => ({
  auth: { isAdmin: true, member: { id: 1, email: "admin@example.com" } },
  getMembers: vi.fn(), inviteMember: vi.fn(), updateMember: vi.fn(), post: vi.fn(),
}));

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/components/NavigationBar", () => ({ NavigationBar: () => null }));
vi.mock("@/components/AuthLayout", () => ({
  AuthLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AUTH_LINK_CLASS: "", AUTH_ERROR_CLASS: "", AUTH_SUBMIT_BUTTON_CLASS: "",
}));
vi.mock("@/lib/member-api", () => ({ getMembers, inviteMember, updateMember }));
vi.mock("@/lib/api-client", () => ({ apiUtils: { post } }));

const member = { id: 2, email: "member@example.com", role: "user", is_active: true, is_verified: true };
beforeEach(() => {
  vi.clearAllMocks();
  auth.isAdmin = true;
  getMembers.mockResolvedValue([{ ...member, id: 1, email: auth.member.email, role: "admin" }, member]);
  inviteMember.mockResolvedValue({ message: "Invitation sent." });
  updateMember.mockResolvedValue(member);
  post.mockResolvedValue({ message: "Accepted" });
});
afterEach(cleanup);

it("shows member access without offering administrator controls", () => {
  auth.isAdmin = false;
  render(<MemoryRouter><Account /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "Send invitation" })).toBeNull();
  expect(getMembers).not.toHaveBeenCalled();
  expect(screen.getByText(/All active members can view/)).toBeTruthy();
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
  vi.restoreAllMocks();
});

it("requires an invitation link before offering account creation", () => {
  render(<MemoryRouter initialEntries={["/register"]}><Registration /></MemoryRouter>);
  expect(screen.queryByLabelText("Password")).toBeNull();
  expect(screen.getByText(/Ask your organization's administrator/)).toBeTruthy();
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
