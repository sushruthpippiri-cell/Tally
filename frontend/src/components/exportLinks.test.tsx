import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { setAccessToken } from "../lib/session";
import { company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const applied: Schemas["FiltersApplied"] = {
  date_from: "2025-04-01",
  date_to: "2026-03-16",
  granularity: "month",
  group_by: "ledger",
  include_cancelled: false,
  include_missing: false,
  by: [],
  not_applicable: [],
};

function salesMetric(): Schemas["MetricOut"] {
  return {
    metric: "sales",
    filters_applied: applied,
    company_timezone: "Asia/Kolkata",
    summary: { amount: "1000.00", available: true, unavailable_count: 0, unavailable_ledgers: [] },
    series: [],
    breakdown: [],
    notes: [],
  };
}

let downloads: string[];
let requests: URL[];
let auth: string | null;

beforeEach(() => {
  downloads = [];
  requests = [];
  auth = null;
  URL.createObjectURL = () => "blob:export";
  URL.revokeObjectURL = () => undefined;
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  };
});

function serveExports(status = 200): void {
  server.use(
    http.get("*/api/companies/c-1/exports/:report", ({ request }) => {
      requests.push(new URL(request.url));
      auth = request.headers.get("Authorization");
      if (status !== 200) {
        return HttpResponse.json({ code: "FORBIDDEN", message: "Not permitted" }, { status });
      }
      return HttpResponse.text("﻿Report,Total Sales Revenue\r\n");
    }),
  );
}

function sales(): void {
  serveCompanies(company());
  for (const metric of ["sales", "product-revenue", "product-difference"]) {
    serve(`/analytics/${metric}`, {
      ...salesMetric(),
      metric,
      label: metric === "product-difference" ? "Product Attribution Difference" : null,
    });
  }
}

describe("exporting a view (EXP-1.1-1.6)", () => {
  it("downloads the view's own report, with its filters and the signed-in user's token", async () => {
    sales();
    serveExports();
    const user = userEvent.setup();
    renderApp("/c/c-1/sales?from=2025-04-01&to=2025-06-30&customer=cust-1");
    const section = await screen.findByRole("region", { name: "Total Sales Revenue" });
    await user.click(within(section).getByRole("button", { name: "Export CSV" }));
    await expect.poll(() => downloads).toEqual(["sales.csv"]);
    const [sent] = requests;
    expect(sent?.pathname).toBe("/api/companies/c-1/exports/sales");
    expect(sent?.searchParams.get("format")).toBe("csv");
    expect(sent?.searchParams.get("from")).toBe("2025-04-01");
    expect(sent?.searchParams.get("to")).toBe("2025-06-30");
    expect(sent?.searchParams.get("customer")).toBe("cust-1");
    expect(sent?.searchParams.get("group_by")).toBe("ledger");
    expect(auth).toBe("Bearer test-token");
  });

  it("asks for a PDF when that is the button pressed", async () => {
    sales();
    serveExports();
    const user = userEvent.setup();
    renderApp("/c/c-1/sales");
    const section = await screen.findByRole("region", { name: "Total Sales Revenue" });
    await user.click(within(section).getByRole("button", { name: "Export PDF" }));
    await expect.poll(() => downloads).toEqual(["sales.pdf"]);
    expect(requests[0]?.searchParams.get("format")).toBe("pdf");
  });

  it("every analytics section offers both formats", async () => {
    sales();
    serveExports();
    renderApp("/c/c-1/sales");
    // Sales shows three figures (EXP-1.4), each with its own file.
    await screen.findByRole("region", { name: "Product Attribution Difference" });
    await expect.poll(() => screen.getAllByRole("button", { name: "Export CSV" }).length).toBe(3);
    expect(screen.getAllByRole("button", { name: "Export PDF" })).toHaveLength(3);
  });

  it("shows the server's refusal instead of a broken file", async () => {
    sales();
    serveExports(403);
    const user = userEvent.setup();
    renderApp("/c/c-1/sales");
    const section = await screen.findByRole("region", { name: "Total Sales Revenue" });
    await user.click(within(section).getByRole("button", { name: "Export CSV" }));
    // The catalogue's own wording for FORBIDDEN (P13.5), not a raw status code.
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Your role in this company does not allow this.",
    );
    expect(downloads).toEqual([]);
  });

  it("a drill-down exports the same rows it is showing, narrowing and all", async () => {
    serveCompanies(company());
    serve("/analytics/sales/drilldown", {
      metric: "sales",
      filters_applied: applied,
      total: "99.99",
      total_rows: 0,
      page: 1,
      page_size: 50,
      rows: [],
    } satisfies Schemas["DrilldownOut"]);
    serveExports();
    const user = userEvent.setup();
    renderApp("/c/c-1/analytics/sales/drilldown?by=ledger%3Al-1");
    await user.click(await screen.findByRole("button", { name: "Export CSV" }));
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]?.pathname).toBe("/api/companies/c-1/exports/sales");
    expect(requests[0]?.searchParams.getAll("by")).toEqual(["ledger:l-1"]);
  });
});
