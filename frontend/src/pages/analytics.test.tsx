import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { periodPresets } from "../lib/filters";
import { setAccessToken } from "../lib/session";
import { accountant, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { withMockApi } from "../test/server";

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

function figure(amount: string | null, extra: Partial<Schemas["Figure"]> = {}): Schemas["Figure"] {
  return {
    amount,
    available: amount !== null,
    unavailable_count: 0,
    unavailable_ledgers: [],
    ...extra,
  };
}

function metric(name: string, extra: Partial<Schemas["MetricOut"]> = {}): Schemas["MetricOut"] {
  return {
    metric: name,
    filters_applied: applied,
    company_timezone: "Asia/Kolkata",
    summary: figure("1000.00"),
    series: [],
    breakdown: [],
    notes: [],
    ...extra,
  };
}

function row(amount: string, n: number): Schemas["DrillRow"] {
  return {
    voucher_id: `v-${n}`,
    voucher_date: "2025-05-02",
    voucher_number: `SI/${n}`,
    voucher_type_name: "Sales",
    base_voucher_type: "SALES",
    ledger_id: "l-sales",
    ledger_name: "Sales - Retail",
    amount,
    dimensions: {},
    custom_fields: n === 1 ? { salesman: "Ravi" } : null,
  };
}

describe("the money on analytics pages is the backend's (D-051 #5)", () => {
  it("a drill-down shows the backend's total even when its rows add up to something else", async () => {
    serveCompanies(company());
    // the rows on screen add up to ₹100.00; the backend says the figure is ₹99.99
    serve("/analytics/sales/drilldown", {
      metric: "sales",
      filters_applied: applied,
      total: "99.99",
      total_rows: 2,
      page: 1,
      page_size: 50,
      rows: [row("60.00", 1), row("40.00", 2)],
    } satisfies Schemas["DrilldownOut"]);
    renderApp("/c/c-1/analytics/sales/drilldown");
    expect(await screen.findByText("₹99.99")).toBeInTheDocument();
    expect(screen.queryByText("₹100.00")).not.toBeInTheDocument();
    // DR-UDF-2: the mapped custom field beside its row
    expect(screen.getByRole("columnheader", { name: "Salesman" })).toBeInTheDocument();
    expect(screen.getByText("Ravi")).toBeInTheDocument();
  });

  it("a section shows the backend's figure, never the sum of its breakdown", async () => {
    serveCompanies(company());
    serve(
      "/analytics/purchases",
      metric("purchases", {
        summary: figure("99.99"),
        breakdown: [
          { key: "l-1", label: "Purchase - Goods", figure: figure("60.00") },
          { key: "l-2", label: "Purchase - Packing", figure: figure("40.00") },
        ],
      }),
    );
    serve("/analytics/suppliers", ranking("suppliers"));
    renderApp("/c/c-1/purchases");
    expect(await screen.findByText("₹99.99")).toBeInTheDocument();
    expect(screen.queryByText("₹100.00")).not.toBeInTheDocument();
  });
});

function ranking(kind: "customers" | "suppliers" | "products"): Schemas["RankingOut"] {
  return {
    ranking: kind,
    rank_by: "revenue",
    label: "Top 10",
    is_top_n: true,
    n: 10,
    total_count: 14,
    filters_applied: applied,
    company_timezone: "Asia/Kolkata",
    rows: [{ rank: 1, id: "l-1", name: "Mehta Electricals", amount: "52000.00" }],
    unattributed:
      kind === "products" ? null : { label: "Unattributed Customer Revenue", amount: "4500.00" },
    product_attributed: null,
    difference: null,
    reference_total: { label: "Total Sales Revenue", amount: "56500.00" },
    notes: ["The listed rows are not meant to add up to the total."],
  };
}

describe("required labels and states (P14.5)", () => {
  it("Sales shows exactly one difference label, the backend's (ACC-VAL-1)", async () => {
    serveCompanies(company());
    serve("/analytics/sales", metric("sales"));
    serve("/analytics/product-revenue", metric("product-revenue", { summary: figure("900.00") }));
    serve(
      "/analytics/product-difference",
      metric("product-difference", {
        label: "Product Attribution Difference",
        summary: figure("100.00"),
      }),
    );
    renderApp("/c/c-1/sales");
    expect(
      await screen.findByRole("heading", { name: "Product Attribution Difference" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unattributed \/ Non-product/)).not.toBeInTheDocument();
  });

  it("a filter that does not apply to a figure says so, and Sales points to the customer's revenue", async () => {
    serveCompanies(company());
    const notApplied = { ...applied, customer: "l-1", not_applicable: ["customer"] };
    serve("/analytics/sales", metric("sales", { filters_applied: notApplied }));
    serve("/analytics/product-revenue", metric("product-revenue", { filters_applied: notApplied }));
    serve(
      "/analytics/product-difference",
      metric("product-difference", {
        filters_applied: notApplied,
        label: "Product Attribution Difference",
      }),
    );
    serve("/masters/options", [{ id: "l-1", name: "Mehta Electricals" }]);
    renderApp("/c/c-1/sales?customer=l-1");
    expect(
      await screen.findByText("The customer filter does not apply to Total Sales Revenue."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See this customer's revenue" })).toHaveAttribute(
      "href",
      "/c/c-1/analytics/customer-revenue/drilldown?customer=l-1&by=customer%3Al-1",
    );
  });

  it("an unavailable balance names its ledgers and is never ₹0 (ACC-9.6)", async () => {
    serveCompanies(company());
    const missing = figure(null, { unavailable_count: 1, unavailable_ledgers: ["HDFC Bank"] });
    serve("/analytics/cash-bank-position", metric("cash-bank-position", { summary: missing }));
    for (const m of ["receivables", "payables", "ledger-balances"]) {
      serve(`/analytics/${m}`, metric(m, { summary: figure("0.00", { direction: "Dr" }) }));
    }
    renderApp("/c/c-1/balances");
    expect(await screen.findByText("Missing for: HDFC Bank")).toBeInTheDocument();
    const cash = screen.getByRole("region", { name: "Cash and bank" });
    expect(within(cash).queryByText("₹0.00")).not.toBeInTheDocument();
  });

  it("a ranking is labelled Top N with View All, and Unattributed stands apart (TOPN-1.3)", async () => {
    serveCompanies(company());
    serve("/analytics/customers", ranking("customers"));
    renderApp("/c/c-1/customers");
    expect(await screen.findByRole("heading", { name: /Top 10 customers/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View All" })).toBeInTheDocument();
    expect(screen.getByText("Unattributed Customer Revenue")).toBeInTheDocument();
    expect(
      screen.getByText("The listed rows are not meant to add up to the total."),
    ).toBeInTheDocument();
  });

  it("stock shows its snapshot date, the stale warning and the unit limitation", async () => {
    serveCompanies(company());
    serve("/analytics/stock", {
      today: "2026-03-16",
      books_from: "2025-04-01",
      period_days: 90,
      period_from: "2025-12-17",
      period_to: "2026-03-16",
      basis: "value",
      fast_percentile: 75,
      fast_threshold: "1000.00",
      classes: [{ key: "NEVER_SOLD", label: "No sale since 1 Apr 2025", count: 1 }],
      total_items: 1,
      items: [
        {
          stock_item_id: "s-1",
          name: "Saffron 1g",
          movement_class: "NEVER_SOLD",
          label: "No sale since 1 Apr 2025",
          note: null,
          stock: "15.000000",
          stock_unit: "Nos",
          snapshot_date: "2026-03-10",
          last_sale_date: null,
          days_since_last_sale: null,
          period_sales_value: "0",
          period_quantities: [],
          multi_unit: false,
        },
      ],
      snapshot_dates: { oldest: "2026-03-10", newest: "2026-03-10" },
      warnings: ["The newest stock snapshot is from 10 Mar 2026."],
      notes: [],
      limitations: ["Quantities are in each item's own unit."],
      unverified_gates: ["G18", "G27"],
    } satisfies Schemas["StockOut"]);
    renderApp("/c/c-1/stock");
    expect(
      await screen.findByText("The newest stock snapshot is from 10 Mar 2026."),
    ).toBeInTheDocument();
    expect(screen.getByText("Quantities are in each item's own unit.")).toBeInTheDocument();
    expect(screen.getByText("15 Nos")).toBeInTheDocument();
    expect(screen.getAllByText("10 Mar 2026").length).toBeGreaterThan(0);
  });

  it("aging lists a party without bill details apart", async () => {
    serveCompanies(company());
    const zero = "0.00";
    serve("/analytics/aging", {
      side: "receivable",
      as_of: "2026-03-16",
      company_timezone: "Asia/Kolkata",
      bucket_order: [{ key: "0-30", label: "Overdue 0-30 days" }],
      total: {
        ledger_id: null,
        ledger_name: null,
        buckets: { "0-30": zero },
        bucket_total: zero,
        credit: zero,
        unadjusted_advances: zero,
        on_account: zero,
        unmatched_settlements: zero,
        net_exposure: zero,
      },
      parties: [],
      no_bill_details: [
        {
          ledger_id: "l-9",
          ledger_name: "Cash Customer",
          balance: figure("500.00", { direction: "Dr" }),
          note: "bill details not available",
        },
      ],
      unverified_gates: ["G25", "G31"],
    } satisfies Schemas["AgingOut"]);
    renderApp("/c/c-1/aging");
    expect(await screen.findByText("bill details not available")).toBeInTheDocument();
  });

  it("payment behaviour says insufficient history", async () => {
    serveCompanies(company());
    serve("/analytics/payment-behaviour", {
      available: true,
      window_from: "2025-03-16",
      window_to: "2026-03-16",
      min_settlements: 3,
      overall: null,
      customers: [
        {
          ledger_id: "l-1",
          ledger_name: "Mehta Electricals",
          settlements: 1,
          settled_amount: "1000.00",
          avg_days_to_pay: null,
          avg_days_past_due: null,
          insufficient_history: true,
        },
      ],
      excluded_settlements: {},
      notes: [],
      unverified_gates: [],
    } satisfies Schemas["PaymentBehaviourOut"]);
    renderApp("/c/c-1/payment-behaviour");
    expect(await screen.findByText("insufficient history")).toBeInTheDocument();
  });
});

describe("a voucher (FR-DD-1)", () => {
  const voucher: Schemas["VoucherDetailOut"] = {
    voucher_id: "v-1",
    tally_guid: "g-1",
    alter_id: 7,
    voucher_number: "SI/001",
    voucher_date: "2025-05-02",
    voucher_type_name: "Sales",
    base_voucher_type: "SALES",
    status: "ACTIVE",
    narration: null,
    last_synced_at: "2026-03-16T06:30:00Z",
    entries: [
      {
        line: 1,
        ledger_id: "l-1",
        ledger_name: "Mehta Electricals",
        direction: "Dr",
        amount: "1050.00",
        bills: [
          {
            allocation_type: "NEW_REF",
            reference_name: "SI/001",
            due_date: "2025-06-01",
            amount: "1050.00",
            direction: "Dr",
          },
        ],
        cost_centres: [],
      },
    ],
    items: [],
    custom_fields: [{ field_key: "salesman", tally_field: "TA_Salesman", value: "Ravi" }],
  };

  it("shows its entries and custom fields, and its history to an Owner", async () => {
    serveCompanies(company());
    serve("/vouchers/v-1", voucher);
    serve("/audit", [
      {
        id: 1,
        created_at: "2026-03-16T06:30:00Z",
        user_id: null,
        action: "VOUCHER_MODIFIED",
        entity_type: "voucher",
        entity_id: "v-1",
        before: { status: "ACTIVE" },
        after: { alter_id: 7 },
        data_range: null,
        result: "SUCCESS",
      },
    ] satisfies Schemas["AuditEntryOut"][]);
    renderApp("/c/c-1/vouchers/v-1");
    expect(await screen.findByRole("heading", { name: "Sales SI/001" })).toBeInTheDocument();
    expect(screen.getByText("Ravi")).toBeInTheDocument();
    expect(await screen.findByText(/VOUCHER_MODIFIED/)).toBeInTheDocument();
  });

  it("has no history for an Accountant (VIEW_LOGS is Owner and Admin)", async () => {
    serveCompanies(accountant());
    serve("/vouchers/v-1", voucher);
    renderApp("/c/c-1/vouchers/v-1");
    expect(await screen.findByRole("heading", { name: "Sales SI/001" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "History" })).not.toBeInTheDocument();
  });
});

describe("period presets (FR-4.1)", () => {
  it("follow the financial year, across its boundary", () => {
    expect(periodPresets("2026-03-16", "2025-04-01")).toEqual([
      { label: "This financial year", from: "2025-04-01", to: "2026-03-16" },
      { label: "Last financial year", from: "2024-04-01", to: "2025-03-31" },
      { label: "This quarter", from: "2026-01-01", to: "2026-03-16" },
      { label: "This month", from: "2026-03-01", to: "2026-03-16" },
      { label: "Last month", from: "2026-02-01", to: "2026-02-28" },
    ]);
    const april = periodPresets("2026-04-01", "2025-04-01");
    expect(april[0]).toEqual({
      label: "This financial year",
      from: "2026-04-01",
      to: "2026-04-01",
    });
    expect(april[2]).toEqual({ label: "This quarter", from: "2026-04-01", to: "2026-04-01" });
    expect(april[4]).toEqual({ label: "Last month", from: "2026-03-01", to: "2026-03-31" });
    // a leap February, and a year starting in January
    expect(periodPresets("2024-03-05", "2020-01-01")[4]).toEqual({
      label: "Last month",
      from: "2024-02-01",
      to: "2024-02-29",
    });
  });
});
