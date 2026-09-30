import { expect, test } from "@playwright/test";

const email = process.env.LIVE_EMAIL ?? "";
const password = process.env.LIVE_PASSWORD ?? "";

test.skip(!email || !password, "set LIVE_EMAIL and LIVE_PASSWORD (a real user)");

test("sign in, reload, sign out against the real backend", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();
  const [cookie] = (await context.cookies()).filter((c) => c.name === "tally_refresh");
  expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict" });

  await page.reload(); // only the HttpOnly cookie survives a reload
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
