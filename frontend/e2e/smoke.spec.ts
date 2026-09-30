import { expect, test } from "@playwright/test";
import { expectNoHorizontalScroll, watchCsp } from "./fixtures";

test("the app loads under its CSP and fits the screen", async ({ page }) => {
  const violations = await watchCsp(page);
  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page).toHaveURL(/\/login$/);
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});
