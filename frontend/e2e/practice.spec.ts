import { expect, test } from "@playwright/test";
import { PASSWORD } from "./helpers";

async function newStudent(page: import("@playwright/test").Page) {
  await page.goto("/register");
  await page.getByLabel("Email", { exact: true }).fill(`e2e-${Date.now()}@example.test`);
  await page.getByLabel(/Password/).fill(PASSWORD);
  await page.getByLabel("No", { exact: true }).check();
  await page.getByLabel(/I have read the privacy notice/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/profile/);
}

test("exam day: admit card, instructions, OMR particulars, sealed booklet, then a scorecard", async ({ page }) => {
  await newStudent(page);
  await page.goto("/practice");
  await expect(page.getByText("Fresh questions waiting for you")).toBeVisible();
  await page.getByRole("button", { name: /Mini NEET mock/ }).click();
  await page.getByLabel("Questions per section").selectOption("5");
  await page.getByLabel(/Strict OMR mode/).check();
  await page.getByRole("button", { name: "Prepare my paper" }).click();

  // 1. Admit card: the clock has not started yet.
  await expect(page.getByRole("heading", { name: "Admit card" })).toBeVisible();
  const roll = (await page.locator("dd.font-mono").first().textContent())!.trim();
  expect(roll).toMatch(/^\d{10}$/);
  await page.getByRole("button", { name: "Continue to instructions" }).click();
  // 2. Instructions
  await expect(page.getByRole("heading", { name: /Important instructions to candidates/i })).toBeVisible();
  await page.getByLabel("I have read and understood the instructions.").check();
  await page.getByRole("button", { name: /Fill OMR particulars/ }).click();
  // 3. OMR particulars must match the admit card and the booklet code.
  const code = (await page.getByText(/^[QRS][1-4]$/).first().textContent())!.trim();
  const begin = page.getByRole("button", { name: "Break the seal and begin" });
  await page.getByPlaceholder("10 digits").fill(roll);
  await expect(begin).toBeDisabled();
  await page.getByRole("radio", { name: code[0], exact: true }).click();
  await page.getByRole("radio", { name: code[1], exact: true }).click();
  await page.getByLabel(/Use full screen/).uncheck();
  await begin.click();

  // The exam room: booklet, OMR sheet, timer.
  await expect(page.getByRole("timer")).toHaveText(/^(19|20):\d\d$/);
  await expect(page.getByText(`Booklet ${code}`)).toBeVisible();
  await page.getByRole("button", { name: "Question 1, option 2" }).click();
  await expect(page.getByRole("button", { name: "Question 1, option 2" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Question 1, option 3" }).click();  // strict mode: no change allowed
  await expect(page.getByText(/a filled bubble cannot be changed/).first()).toBeVisible();
  await page.getByRole("tab", { name: /Zoology/ }).click();
  await expect(page.locator("#qnum")).toHaveText("16.");
  await page.getByRole("button", { name: "Rough work" }).click();
  await expect(page.getByRole("dialog", { name: "Rough work" })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: "Submit" }).click();
  await page.getByRole("button", { name: "Yes, submit" }).click();
  await expect(page.getByText("Scorecard")).toBeVisible();
  await expect(page.getByRole("heading", { name: "By section" })).toBeVisible();
  await page.getByRole("button", { name: "all" }).click();
  await expect(page.getByText(/✓ correct/).first()).toBeVisible();
  await page.getByRole("button", { name: "Report a problem" }).first().click();
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Thanks — reported/)).toBeVisible();
});

test("student builds a class-based study plan and ticks off a task", async ({ page }) => {
  await newStudent(page);
  await page.goto("/study-plan");
  await page.getByLabel("Your class").selectOption("11");
  await page.getByRole("button", { name: "Build my plan" }).click();
  await expect(page.getByText(/Class 11 · NEET on .* \(estimated\)/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /This week/ })).toBeVisible();
  const first = page.getByRole("checkbox", { name: /Mark "Learn: / }).first();
  await first.check();
  await expect(first).toBeChecked();
  await page.getByRole("button", { name: /^Zoology/ }).click();
  await expect(page.getByLabel("Status of Animal Kingdom")).toBeVisible();
});
