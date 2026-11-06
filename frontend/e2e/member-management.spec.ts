import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import type { Member, Role } from "../src/lib/member-types";
import { accessToken, loginWithEmail, PASSWORD } from "./helpers/auth";

const mailpit = process.env.MAILPIT_BASE_URL ?? "http://localhost:8025";

async function accountFixture(page: Page) {
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Members", exact: true })).toBeVisible();
  const token = await accessToken(page);
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const email = `member-removal-${randomUUID().slice(0, 12)}@example.com`;
  const read = async () => {
    const response = await page.request.get("/api/v1/members", { headers });
    expect(response.ok(), await response.text()).toBe(true);
    return await response.json() as Member[];
  };
  const row = page.getByRole("list", { name: "Members", exact: true }).getByRole("listitem").filter({ hasText: email });
  const invite = async () => {
    await page.getByRole("button", { name: "Invite member", exact: true }).click();
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByRole("button", { name: "Send invitation", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Invitation sent");
    await expect(row).toBeVisible();
    const member = (await read()).find(member => member.email === email);
    expect(member).toBeTruthy();
    return member!;
  };
  const disable = async () => {
    await row.getByRole("button", { name: "Disable", exact: true }).click();
    await page.getByRole("dialog", { name: "Disable access?", exact: true }).getByRole("button", { name: "Disable access", exact: true }).click();
    await expect(row.getByText("Disabled", { exact: true })).toBeVisible();
  };
  return { email, headers, row, read, invite, disable,
    cleanup: async () => {
      for (const member of (await read()).filter(member => member.email === email)) {
        const path = `/api/v1/members/${member.id}`;
        if (member.is_active) {
          const disabled = await page.request.put(path, { headers, data: { role: member.role, is_active: false } });
          expect(disabled.ok(), await disabled.text()).toBe(true);
        }
        const removed = await page.request.delete(path, { headers });
        expect(removed.status(), await removed.text()).toBe(204);
      }
    },
  };
}

async function invitationLink(page: Page, email: string, previous?: string) {
  let link = "";
  await expect.poll(async () => {
    const response = await page.request.get(`${mailpit}/api/v1/messages`);
    expect(response.ok()).toBe(true);
    const { messages } = await response.json() as { messages: { ID: string; To: { Address: string }[] }[] };
    for (const message of messages.filter(message => message.To.some(recipient => recipient.Address === email))) {
      const detail = await page.request.get(`${mailpit}/api/v1/message/${message.ID}`);
      expect(detail.ok()).toBe(true);
      const { Text } = await detail.json() as { Text: string };
      const match = Text.match(/https?:\/\/[^\s]+\/register#token=[A-Za-z0-9_-]+/);
      if (match) {
        // Keep navigation on the test deployment even behind a differently named ingress.
        const invitation = new URL(match[0]);
        const candidate = new URL(invitation.pathname + invitation.hash, page.url()).href;
        if (candidate !== previous) {
          link = candidate;
          return true;
        }
      }
    }
    return false;
  }, { message: "An invitation should arrive in the local mail sink" }).toBe(true);
  return link;
}

async function acceptInvitation(page: Page, link: string, email: string) {
  await page.goto(link);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Accept invitation", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Your account is ready");
  await page.getByRole("link", { name: "Log in", exact: true }).click();
  await loginWithEmail(page, email, { rememberMe: true });
}

test("removes a disabled invitation after confirmation and retains shared data", async ({ page }, testInfo) => {
  const fixture = await accountFixture(page);
  try {
    const catalogue = await page.request.get("/api/v1/system", { headers: fixture.headers });
    expect(catalogue.ok()).toBe(true);
    const original = await catalogue.json();
    const pending = await fixture.invite();
    expect(pending.is_verified).toBe(false);
    await expect(fixture.row.getByRole("button", { name: "Remove", exact: true })).toHaveCount(0);
    const active = await page.request.delete(`/api/v1/members/${pending.id}`, { headers: fixture.headers });
    expect(active.status()).toBe(409);
    await fixture.disable();

    for (const [theme, width, height] of [["Light", 1280, 900], ["Dark", 1280, 900], ["Dark", 320, 568]] as const) {
      await page.setViewportSize({ width, height });
      // Account is open in the settings overlay, so switch theme from its Preferences section.
      const settings = page.getByRole("dialog", { name: "Settings", exact: true });
      await settings.getByRole("button", { name: "Preferences", exact: true }).click();
      await settings.getByRole("radio", { name: theme, exact: true }).check();
      await settings.getByRole("button", { name: "Account", exact: true }).click();
      await expect(fixture.row.getByText("Disabled", { exact: true })).toBeVisible();
      await fixture.row.getByRole("button", { name: "Remove", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Remove member?", exact: true });
      await expect(dialog).toContainText(fixture.email);
      await expect(dialog).toContainText("new invitation");
      await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
      const bounds = await dialog.boundingBox();
      expect(bounds).toBeTruthy();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.y).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(height);
      expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      await dialog.screenshot({ path: testInfo.outputPath(`member-removal-${theme.toLowerCase()}-${width}.png`) });
      await page.keyboard.press("Tab");
      await expect(dialog.getByRole("button", { name: "Remove member", exact: true })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(fixture.row.getByRole("button", { name: "Remove", exact: true })).toBeFocused();
    }
    await fixture.row.getByRole("button", { name: "Remove", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Remove member?", exact: true });
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(fixture.row).toBeVisible();
    expect((await fixture.read()).some(member => member.id === pending.id)).toBe(true);
    await fixture.row.getByRole("button", { name: "Remove", exact: true }).click();
    await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(fixture.row).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Members", exact: true })).toBeFocused();
    await expect(page.getByRole("status")).toContainText("has been removed");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Members", exact: true })).toBeVisible();
    await expect(fixture.row).toHaveCount(0);
    const retained = await page.request.get("/api/v1/system", { headers: fixture.headers });
    expect(retained.ok()).toBe(true);
    expect(await retained.json()).toMatchObject({ revision: original.revision, document: original.document });
  } finally {
    await fixture.cleanup();
  }
});

test("enforces current access during removal and keeps previous sessions invalid after reinvitation", async ({ page, browser }) => {
  const fixture = await accountFixture(page);
  const memberContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const memberPage = await memberContext.newPage();
  try {
    const initial = await fixture.invite();
    const firstLink = await invitationLink(page, fixture.email);
    await acceptInvitation(memberPage, firstLink, fixture.email);
    const oldToken = await accessToken(memberPage);
    const oldHeaders = { Authorization: `Bearer ${oldToken}` };
    expect((await memberContext.cookies()).some(cookie => cookie.name === "off_key_remembered_session")).toBe(true);
    await memberPage.goto(new URL("/account", page.url()).href);
    await expect(memberPage.getByRole("heading", { name: "Account", exact: true })).toBeVisible();
    await expect(memberPage.getByRole("region", { name: "Signed in", exact: true })).toContainText("Member");
    await expect(memberPage.getByRole("heading", { name: "Members", exact: true })).toHaveCount(0);
    const forbidden = await memberPage.request.delete(new URL(`/api/v1/members/${initial.id}`, page.url()).href, { headers: oldHeaders });
    expect(forbidden.status()).toBe(403);
    await page.reload();
    await fixture.disable();
    await fixture.row.getByRole("button", { name: "Remove", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Remove member?", exact: true });
    const enabled = await page.request.put(`/api/v1/members/${initial.id}`, { headers: fixture.headers, data: { role: "user", is_active: true } });
    expect(enabled.ok()).toBe(true);
    await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("Disable this member");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.reload();
    await expect(fixture.row.getByText("Active", { exact: true })).toBeVisible();
    await fixture.disable();
    await fixture.row.getByRole("button", { name: "Remove", exact: true }).click();
    await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
    await expect(fixture.row).toHaveCount(0);
    const denied = await memberPage.request.get(new URL("/api/v1/members/me", page.url()).href, { headers: oldHeaders });
    expect(denied.status()).toBe(401);
    const refresh = await memberPage.request.post(new URL("/api/v1/auth/refresh", page.url()).href, { headers: { "X-Off-Key-Session": "1" } });
    expect(refresh.status()).toBe(401);
    const replacement = await fixture.invite();
    expect(replacement.id).not.toBe(initial.id);
    const freshLink = await invitationLink(page, fixture.email, firstLink);
    const expired = await page.request.post("/api/v1/auth/accept-invitation", { data: { token: new URL(firstLink).hash.slice("#token=".length), password: PASSWORD } });
    expect(expired.status()).toBe(422);
    await acceptInvitation(memberPage, freshLink, fixture.email);
    const stillDenied = await memberPage.request.get(new URL("/api/v1/members/me", page.url()).href, { headers: oldHeaders });
    expect(stillDenied.status()).toBe(401);
  } finally {
    await memberContext.close();
    await fixture.cleanup();
  }
});

test("a custom role grants its member exactly the permissions it bundles", async ({ page, browser }) => {
  const fixture = await accountFixture(page);
  const name = `Operator ${randomUUID().slice(0, 8)}`;
  const memberContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const memberPage = await memberContext.newPage();
  const readRole = async () => {
    const response = await page.request.get("/api/v1/roles", { headers: fixture.headers });
    expect(response.ok(), await response.text()).toBe(true);
    return (await response.json() as Role[]).find(role => role.name === name);
  };
  try {
    const roles = page.getByRole("region", { name: "Roles", exact: true });
    await roles.getByRole("button", { name: "New role", exact: true }).click();
    const form = roles.getByRole("form", { name: "New role", exact: true });
    await form.getByLabel("Name", { exact: true }).fill(name);
    await form.getByRole("checkbox", { name: /Manage monitors/ }).check();
    await form.getByRole("button", { name: "Create role", exact: true }).click();
    await expect(roles.getByRole("status")).toContainText(`${name} created.`);
    expect(await readRole()).toMatchObject({ permissions: ["manage_monitors"], built_in: false, members: 0 });

    const members = page.getByRole("region", { name: "Members", exact: true });
    await members.getByRole("button", { name: "Invite member", exact: true }).click();
    await members.getByLabel("Email", { exact: true }).fill(fixture.email);
    await members.getByLabel("Role", { exact: true }).selectOption({ label: name });
    await members.getByRole("button", { name: "Send invitation", exact: true }).click();
    await expect(members.getByRole("status")).toContainText("Invitation sent");
    await acceptInvitation(memberPage, await invitationLink(page, fixture.email), fixture.email);

    const api = (path: string) => new URL(`/api/v1${path}`, page.url()).href;
    const memberHeaders = { Authorization: `Bearer ${await accessToken(memberPage)}` };
    const profile = await memberPage.request.get(api("/members/me"), { headers: memberHeaders });
    expect(await profile.json()).toMatchObject({ role: (await readRole())!.id, permissions: ["manage_monitors"] });
    await memberPage.goto(new URL("/account", page.url()).href);
    const signedIn = memberPage.getByRole("region", { name: "Signed in", exact: true });
    await expect(signedIn).toContainText(name);
    await expect(signedIn).toContainText("Your role: view organization data, manage monitors.");
    await expect(memberPage.getByRole("heading", { name: "Members", exact: true })).toHaveCount(0);
    await expect(memberPage.getByRole("heading", { name: "Roles", exact: true })).toHaveCount(0);
    const forbidden = await memberPage.request.post(api("/roles"), { headers: memberHeaders, data: { name: "Escalated", permissions: ["manage_members"] } });
    expect(forbidden.status()).toBe(403);

    // A role cannot be deleted while a member holds it.
    const role = (await readRole())!;
    expect(role.members).toBe(1);
    const held = await page.request.delete(`/api/v1/roles/${role.id}`, { headers: fixture.headers });
    expect(held.status(), await held.text()).toBe(409);
  } finally {
    await memberContext.close();
    await fixture.cleanup();
    const role = await readRole();
    if (role) {
      const removed = await page.request.delete(`/api/v1/roles/${role.id}`, { headers: fixture.headers });
      expect(removed.status(), await removed.text()).toBe(204);
    }
  }
});
