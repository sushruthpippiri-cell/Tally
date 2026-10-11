import { expect, test, type Locator } from "@playwright/test";
import { expectNoHorizontalScroll, watchCsp } from "./fixtures";
import { mockApi } from "./mockApi";

/** SRS 20's review use cases (UC-10, UC-12, UC-14) as a user does them, on desktop and on the
 * 360 px touch project. docs/use-case-coverage.md maps each to the other tests that answer it. */
async function press(target: Locator, mobile: boolean): Promise<void> {
  if (mobile) await target.tap();
  else await target.click();
}

test("UC-10: the Accountant reads a FAIL with both values, the difference and what was not compared", async ({
  page,
}) => {
  const violations = await watchCsp(page);
  await mockApi(page);
  await page.goto("/c/c-1/reconciliation");
  const table = page.getByRole("table", { name: "Comparisons with Tally" });
  const failing = table.getByRole("row").filter({ hasText: "FAIL" });
  await expect(failing).toHaveCount(1);
  // the backend's difference, beside both of the values it was taken between
  await expect(failing).toContainText("₹12.34");
  await expect(failing).toContainText("1,23,45,67,89,012.34");
  await expect(failing).toContainText("1,23,45,67,89,000.00");
  // and the ledger the run could not compare, with the reason, so it is not mistaken for a pass
  await expect(page.getByText("opening balance unavailable (Data Quality)")).toBeVisible();
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});

// @req_partial NFR-UI-2, AC-65 - the Difference drill-down by touch; changing a filter by touch is not covered
test("UC-12: the Difference section opens the vouchers that hold revenue not tied to a stock item", async ({
  page,
}, info) => {
  const mobile = info.project.name === "mobile";
  const violations = await watchCsp(page);
  await mockApi(page);
  await page.goto("/c/c-1/sales");
  await press(
    page.getByRole("link", { name: "See every voucher behind Product Attribution Difference" }),
    mobile,
  );
  await expect(page).toHaveURL(/\/analytics\/product-difference\/drilldown/);
  await expect(page.getByRole("link", { name: "SI/2025-26/00001" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});

test("UC-14: the Admin opens a data-quality check, reads how to fix it and sees the records", async ({
  page,
}, info) => {
  const mobile = info.project.name === "mobile";
  const violations = await watchCsp(page);
  await mockApi(page);
  await page.goto("/c/c-1/data-quality");
  const check = page.getByRole("listitem").filter({ hasText: "Sync held back by failing records" });
  await expect(check).toContainText("3 · ERROR");
  await expect(check).toContainText("Fix these records in Tally; the next sync moves past them.");
  await press(check.getByRole("button", { name: /Show the 3 items/ }), mobile);
  await expect(check.getByText("PARSE_ERROR")).toBeVisible();
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});
