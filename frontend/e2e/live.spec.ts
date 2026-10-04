import { expect, test } from "@playwright/test";

const email = process.env.LIVE_EMAIL ?? "";
const password = process.env.LIVE_PASSWORD ?? "";

test.skip(!email || !password, "set LIVE_EMAIL and LIVE_PASSWORD (a real user)");

test("sign in, reload, sign out against the real backend", async ({ page, context }) => {
  // Signed in, whatever the user's companies: none or several (the list) or one (its Home).
  const signedIn = page.getByRole("button", { name: "Sign out" }).first();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(signedIn).toBeVisible();
  const [cookie] = (await context.cookies()).filter((c) => c.name === "tally_refresh");
  expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict" });

  await page.reload(); // only the HttpOnly cookie survives a reload
  await expect(signedIn).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("every page loads against the real backend", async ({ page }) => {
  const errors: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" }).first()).toBeVisible();
  const companies = await page.request.get("/api/companies", {
    headers: { Authorization: `Bearer ${await accessToken(page)}` },
  });
  const [first] = (await companies.json()) as { company_id: string }[];
  test.skip(!first, "the user has no company");
  for (const section of [
    "home",
    "sync",
    "agents",
    "reconciliation",
    "data-quality",
    "settings",
    "users",
  ]) {
    await page.goto(`/c/${first?.company_id}/${section}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Something went wrong|could not be loaded/)).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

/** A fresh access token, the way the app gets one: from the refresh cookie. */
async function accessToken(page: import("@playwright/test").Page): Promise<string> {
  const r = await page.request.post("/api/auth/refresh", { headers: { "X-Tally-Request": "1" } });
  return ((await r.json()) as { access_token: string }).access_token;
}
