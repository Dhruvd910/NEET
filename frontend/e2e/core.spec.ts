import { expect, test } from "@playwright/test";
import { latestEmail, PASSWORD, signIn } from "./helpers";

test("landing page carries the guidance-not-guarantee disclaimer", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("NEET Compass gives guidance, not guarantees.")).toBeVisible();
});

test("anonymous predictor groups demo results without probabilities", async ({ page }) => {
  await page.goto("/predictor");
  await page.getByLabel("All India Rank").fill("9000");
  await page.getByRole("button", { name: "Show historical matches" }).click();
  await expect(page.getByRole("heading", { name: /Stronger historical fit|Possible \/ uncertain|Ambitious/ }).first())
    .toBeVisible();
  await expect(page.getByText("DEMO", { exact: false }).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/\d+\s?% chance|guaranteed seat|safe college/i);
});

test("college page shows fees with academic year and demo status", async ({ page }) => {
  await page.goto("/colleges");
  await page.getByRole("link", { name: "Full details" }).first().click();
  await page.getByRole("tab", { name: "Fees & cost" }).click();
  await expect(page.getByText(/20\d\d-\d\d/).first()).toBeVisible();
  await expect(page.getByText("DEMO data — not real").first()).toBeVisible();
});

test("signed-in student can use the assistant (CSRF-protected POST)", async ({ page }) => {
  await signIn(page, "student@demo.test");
  await page.goto("/assistant");
  await page.getByPlaceholder(/Ask anything about NEET-UG/).fill("What documents do I need for counselling?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator("body")).not.toContainText("CSRF");
  await expect(page.getByText(/source|official|bulletin|document/i).last()).toBeVisible({ timeout: 20_000 });
});

test("a minor's account stays locked until the guardian consents by email link", async ({ page, browser }) => {
  const email = `minor-${Date.now()}@example.test`;
  await page.goto("/register");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel(/Password/).fill(PASSWORD);
  await page.getByLabel("Yes").check();
  await page.getByLabel(/guardian's email/i).fill("parent@example.test");
  await page.getByLabel(/I have read the privacy notice/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(/Waiting for your parent or guardian/).first()).toBeVisible();

  const mail = latestEmail();
  expect(mail).toContain("To: parent@example.test");
  const link = mail.match(/https?:\/\/\S+guardian-consent\?token=\S+/)![0];

  const guardian = await (await browser.newContext()).newPage();  // the parent's own browser
  await guardian.goto(link.replace(/^https?:\/\/[^/]+/, "http://localhost:3100"));
  await expect(guardian.getByRole("heading", { name: "Parent or guardian consent" })).toBeVisible();
  await guardian.getByLabel("Your full name").fill("Parent Name");
  await guardian.getByLabel("Relationship to the student").selectOption("mother");
  await guardian.getByLabel(/I am this student's parent or legal guardian/).check();
  await guardian.getByRole("button", { name: "I give consent" }).click();
  await expect(guardian.getByText("Thank you — consent recorded")).toBeVisible();

  await page.reload();
  await expect(page.getByText(/Waiting for your parent or guardian/)).toHaveCount(0);
});

test("admin sees the go-live readiness checklist; students do not see admin", async ({ page }) => {
  await signIn(page, "student@demo.test");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();

  await signIn(page, "admin@demo.test");
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Go-live readiness" })).toBeVisible();
  await expect(page.getByText("DPDP Act 2023 legal review completed")).toBeVisible();
  await page.getByRole("tab", { name: "Eligibility rules" }).click();
  await expect(page.getByRole("heading", { name: /Missing rules/ })).toBeVisible();
});
