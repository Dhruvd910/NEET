import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Seeded demo accounts on the e2e database (password = SEED_DEMO_PASSWORD default from backend/.env.example).
export const PASSWORD = process.env.E2E_PASSWORD ?? "demo-password-123";
const OUTBOX = path.resolve(__dirname, "../../backend/.e2e/storage/outbox");

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.request().method() === "POST"),
    page.getByRole("button", { name: /sign in/i }).click(),
  ]);
  expect(res.status()).toBe(200);
  await expect(page).toHaveURL(/\/(dashboard|profile)/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** Latest email written by the console email backend, e.g. the guardian-consent link. */
export function latestEmail(): string {
  const files = fs.readdirSync(OUTBOX).sort();
  return fs.readFileSync(path.join(OUTBOX, files[files.length - 1]), "utf-8");
}
