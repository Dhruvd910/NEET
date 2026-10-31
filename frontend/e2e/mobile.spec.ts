import { expect, test } from "@playwright/test";

for (const path of ["/", "/predictor", "/colleges", "/neet", "/register"]) {
  test(`no horizontal scrolling on phones: ${path}`, async ({ page }) => {
    await page.goto(path);
    // The footer renders last; dev-server live reload keeps a socket open, so "networkidle" never fires.
    await expect(page.getByText("NEET Compass gives guidance, not guarantees.")).toBeVisible();
    await expect(page.locator("main")).not.toContainText("Loading");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
