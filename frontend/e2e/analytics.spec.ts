import { expect, test, type Locator } from "@playwright/test";
import { SERIES } from "./analyticsMock";
import { expectNoHorizontalScroll, watchCsp } from "./fixtures";
import { mockApi } from "./mockApi";

/** NFR-UI-2 / AC-65: charts, filters and drill-downs work by touch on the 360 px project and by
 * mouse on the desktop one. */
async function press(target: Locator, mobile: boolean): Promise<void> {
  if (mobile) await target.tap();
  else await target.click();
}

test("a chart bar opens its exact figure, then drills into that month's vouchers", async ({
  page,
}, info) => {
  const violations = await watchCsp(page);
  await mockApi(page);
  await page.goto("/c/c-1/sales");
  const chart = page.getByRole("figure").filter({ hasText: "Total Sales Revenue by month" });
  const bars = chart.locator(".recharts-bar-rectangle");
  await expect(bars).toHaveCount(SERIES.length);
  await press(bars.nth(1), info.project.name === "mobile");
  // the backend's own string, formatted: never a number the chart computed
  await expect(chart.getByText("₹24,69,134.89")).toBeVisible();
  await press(chart.getByRole("button", { name: "See vouchers" }), info.project.name === "mobile");
  await expect(page).toHaveURL(/\/analytics\/sales\/drilldown\?from=2025-05-01&to=2025-05-31$/);
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});

test("a period chosen in the filters stays in the URL and in every section link (FR-4.3)", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/c/c-1/sales");
  await page.getByLabel("Period").selectOption("Last financial year");
  await expect(page).toHaveURL(/from=\d{4}-04-01&to=\d{4}-03-31/);
  const search = new URL(page.url()).search;
  // the section menu (the sidebar, or the drawer at 360 px) links with the same filters
  await expect(page.locator(`a[href="/c/c-1/purchases${search}"]`).first()).toBeAttached();
  await expectNoHorizontalScroll(page);
});

test("a breakdown row drills to its vouchers, and a voucher opens by touch (FR-DD-1)", async ({
  page,
}, info) => {
  const mobile = info.project.name === "mobile";
  await mockApi(page);
  await page.goto("/c/c-1/customers");
  await press(page.getByRole("link", { name: /Sri Lakshmi/ }).first(), mobile);
  await expect(page).toHaveURL(/\/analytics\/customer-revenue\/drilldown\?by=customer%3Al-1$/);
  await press(page.getByRole("link", { name: "SI/2025-26/00001" }), mobile);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("SI/2025-26/00001");
  await expect(page.getByText("Ravi")).toBeVisible();
  await expectNoHorizontalScroll(page);
});

test("a section exports to CSV and to PDF, by touch, under the CSP (EXP-1.1)", async ({
  page,
}, info) => {
  const violations = await watchCsp(page);
  const mobile = info.project.name === "mobile";
  await mockApi(page);
  // The export endpoint answers with a real attachment, so the browser performs a download.
  // Registered after mockApi's catch-all, and Playwright matches the newest route first.
  await page.route("**/api/companies/c-1/exports/sales**", (route) => {
    const format = new URL(route.request().url()).searchParams.get("format");
    return route.fulfill({
      status: 200,
      headers: {
        "content-type": format === "pdf" ? "application/pdf" : "text/csv; charset=utf-8",
        "content-disposition": `attachment; filename="sales-2025-04-01-to-2026-03-16.${format}"`,
      },
      body: format === "pdf" ? "%PDF-1.7\n" : "﻿Report,Total Sales Revenue\r\n",
    });
  });
  await page.goto("/c/c-1/sales");
  const section = page.getByRole("region", { name: "Total Sales Revenue" });

  for (const format of ["CSV", "PDF"] as const) {
    const started = page.waitForEvent("download");
    await press(section.getByRole("button", { name: `Export ${format}` }), mobile);
    const file = await started;
    expect(file.suggestedFilename()).toContain(format.toLowerCase());
  }
  await expectNoHorizontalScroll(page);
  expect(violations).toEqual([]);
});
