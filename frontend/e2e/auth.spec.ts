import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { expectNoHorizontalScroll, watchCsp } from "./fixtures";

const COOKIE = "HttpOnly; Secure; SameSite=Strict; Path=/api/auth";

/** A stand-in for the backend's auth endpoints (D-051 #1-2): the browser, not our code, keeps
 * and sends the HttpOnly cookie. */
async function mockAuth(page: Page): Promise<{ refreshes: number }> {
  const seen = { refreshes: 0 };
  const token = (value: string) => JSON.stringify({ access_token: value, expires_in: 1800 });
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "set-cookie": `tally_refresh=r1; Max-Age=86400; ${COOKIE}` },
      body: token("a1"),
    }),
  );
  await page.route("**/api/auth/refresh", async (route) => {
    const headers = await route.request().allHeaders();
    const ok =
      (headers.cookie ?? "").includes("tally_refresh=") && headers["x-tally-request"] === "1";
    seen.refreshes += 1;
    await route.fulfill(
      ok
        ? {
            status: 200,
            contentType: "application/json",
            headers: {
              "set-cookie": `tally_refresh=r${seen.refreshes + 1}; Max-Age=86400; ${COOKIE}`,
            },
            body: token(`a${seen.refreshes + 1}`),
          }
        : { status: 401, contentType: "application/json", body: '{"code":"NOT_AUTHENTICATED"}' },
    );
  });
  await page.route("**/api/auth/logout", (route) =>
    route.fulfill({
      status: 204,
      headers: { "set-cookie": `tally_refresh=; Max-Age=0; ${COOKIE}` },
    }),
  );
  return seen;
}

test("sign in, reload, sign out: the session lives in the HttpOnly cookie", async ({
  page,
  context,
}) => {
  const violations = await watchCsp(page);
  await mockAuth(page);
  await page.goto("/login");
  await expectNoHorizontalScroll(page);
  await page.getByLabel("Email").fill("owner@example.com");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();

  const [cookie] = (await context.cookies()).filter((c) => c.name === "tally_refresh");
  expect(cookie).toMatchObject({
    httpOnly: true,
    secure: true,
    sameSite: "Strict",
    path: "/api/auth",
  });
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  expect(await page.evaluate(() => document.cookie)).toBe(""); // script cannot read it

  await page.reload(); // the access token was only in memory; the cookie restores it
  await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  expect((await context.cookies()).filter((c) => c.name === "tally_refresh")).toEqual([]);
  await page.goto("/companies");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  expect(violations).toEqual([]);
});

test("the built app never touches browser storage (D-051 #1)", () => {
  const assets = join(import.meta.dirname, "..", "dist", "assets");
  for (const file of readdirSync(assets).filter((f) => f.endsWith(".js"))) {
    const code = readFileSync(join(assets, file), "utf-8");
    expect(code, file).not.toMatch(/localStorage|sessionStorage/);
  }
});
