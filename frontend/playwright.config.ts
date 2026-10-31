import { defineConfig, devices } from "@playwright/test";

// Browser tests run against their own API (fresh, seeded SQLite DB) and their own Next.js dev server,
// on ports 8766 / 3100 (production build in .next-e2e), so they never touch the development database
// or a running `npm run dev`.
const PYTHON = process.env.E2E_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3100", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile.spec.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `${PYTHON} ../backend/scripts/e2e_server.py 8766`,
      url: "http://127.0.0.1:8766/api/ready",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      // A production build: what students actually get, and no on-demand compiling during tests.
      command: "npx next build && npx next start -p 3100",
      url: "http://localhost:3100",
      timeout: 400_000,
      reuseExistingServer: false,
      env: { API_ORIGIN: "http://127.0.0.1:8766", NEXT_DIST_DIR: ".next-e2e" },
    },
  ],
});
