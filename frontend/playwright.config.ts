import { defineConfig, devices } from "@playwright/test";
import { env } from "node:process";
import { fileURLToPath } from "node:url";

const isCI = Boolean(env.CI);
const chromiumChannel =
  env.PLAYWRIGHT_CHROMIUM_CHANNEL === "chrome" ? "chrome" : undefined;
const authStateFile = fileURLToPath(
  new URL("./test-results/.auth/user.json", import.meta.url)
);
const chromiumUse = {
  ...devices["Desktop Chrome"],
  ...(chromiumChannel ? { channel: chromiumChannel } : {}),
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  timeout: 180_000,
  expect: {
    timeout: 30_000,
  },
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: isCI ? "off" : "retain-on-failure",
  },
  projects: [
    {
      name: "auth-setup",
      testMatch: /auth\.setup\.ts/,
      use: chromiumUse,
    },
    {
      name: "chromium",
      testIgnore: /.*\.setup\.ts/,
      use: {
        ...chromiumUse,
        storageState: authStateFile,
      },
      dependencies: ["auth-setup"],
    },
  ],
});
