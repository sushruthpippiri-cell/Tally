import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { setAccessToken } from "../lib/session";
import { admin, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

function group(overrides: Partial<Schemas["GroupOut"]>): Schemas["GroupOut"] {
  return {
    group_id: "g",
    tally_guid: "guid",
    name: "Group",
    is_predefined: false,
    reserved_name: null,
    parent_group_id: null,
    predefined_group: null,
    primary_group: null,
    nature: null,
    anchor: null,
    resolution_status: "RESOLVED",
    status: "ACTIVE",
    ...overrides,
  };
}

const setting = (value: unknown, is_default = true) => ({ value, is_default });

function settingsApi() {
  serve("/settings", {
    feature_flags: { FEATURE_ANOMALY_DETECTION: { enabled: false, is_default: true } },
    settings: {
      "classification.sales_groups": setting(
        [
          // renamed in Tally: the current name is shown, the reserved name is what is stored
          {
            type: "PREDEFINED",
            reserved_name: "Sales Accounts",
            display_name: "Sales",
            is_missing: false,
          },
          { type: "COMPANY_GROUP", tally_guid: "gone-guid", display_name: null, is_missing: true },
        ],
        false,
      ),
      "classification.purchase_groups": setting([]),
      "classification.expense_groups": setting([]),
      "classification.cash_bank_groups": setting([]),
      "classification.tax_groups": setting([]),
      "analytics.taxable_value_mode": setting(true),
      "cashflow.include_journal": setting(true),
      "aging.bucket_boundaries": setting([30, 60, 90]),
      "payment.window_days": setting(365),
      "payment.min_settlements": setting(3),
      "stock.measurement_period_days": setting(90),
      "stock.fast_percentile": setting(75),
      "stock.slow_threshold_days": setting(90),
      "stock.dead_stock_days": setting(180),
      "stock.snapshot_stale_days": setting(2),
      "reconciliation.money_absolute_tolerance": setting("1.00"),
      "reconciliation.money_percentage_tolerance": setting("0.01"),
      "reconciliation.quantity_absolute_tolerance": setting("0"),
      "reconciliation.quantity_percentage_tolerance": setting("0.5"),
      "analytics.top_n_default": setting(10),
      "analytics.quarter_mode": setting("financial"),
    },
  });
  serve("/masters/groups", [
    group({
      name: "Sales",
      is_predefined: true,
      reserved_name: "Sales Accounts",
      tally_guid: "p1",
    }),
    group({ name: "Export Sales", tally_guid: "own-guid" }),
    group({ name: "Nested", tally_guid: "n1", parent_group_id: "x" }),
  ]);
}

function captureSettings(): { body: unknown } {
  const seen: { body: unknown } = { body: null };
  server.use(
    http.put("*/api/companies/c-1/settings", async ({ request }) => {
      seen.body = await request.json();
      return HttpResponse.json({ settings: {}, feature_flags: {} });
    }),
  );
  return seen;
}

describe("Settings (P13.8)", () => {
  it("flags allow-list entries no longer in Tally and sends identifiers, never names (D-001)", async () => {
    serveCompanies(company());
    settingsApi();
    const seen = captureSettings();
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Classification" }));
    const sales = within(await screen.findByRole("group", { name: "Sales" }));
    expect(sales.getByText("gone-guid").parentElement).toHaveTextContent("No longer in Tally");
    expect(sales.queryByText("Nested")).not.toBeInTheDocument(); // never an anchor
    await user.click(sales.getByRole("checkbox", { name: /Export Sales/ }));
    await user.click(screen.getByRole("button", { name: "Save classification" }));
    await screen.findByRole("status");
    const body = seen.body as { settings: Record<string, unknown> };
    expect(body.settings["classification.sales_groups"]).toEqual([
      { type: "PREDEFINED", reserved_name: "Sales Accounts" },
      { type: "COMPANY_GROUP", tally_guid: "gone-guid" },
      { type: "COMPANY_GROUP", tally_guid: "own-guid" },
    ]);
  });

  it("sends only changed thresholds, decimals as strings, and shows the server's message by the field", async () => {
    serveCompanies(company());
    settingsApi();
    const seen: { body: unknown } = { body: null };
    server.use(
      http.put("*/api/companies/c-1/settings", async ({ request }) => {
        seen.body = await request.json();
        return HttpResponse.json(
          {
            code: "VALIDATION_ERROR",
            message: "Invalid settings",
            details: {
              errors: [
                {
                  key: "stock.dead_stock_days",
                  message: "must be greater than stock.slow_threshold_days",
                },
              ],
            },
          },
          { status: 422 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Thresholds" }));
    const dead = await screen.findByLabelText(/^Dead stock after/);
    await user.clear(dead);
    await user.type(dead, "60");
    const money = screen.getByLabelText(/^Money: absolute/);
    await user.clear(money);
    await user.type(money, "2.50");
    await user.click(screen.getByRole("button", { name: "Save thresholds" }));
    expect(
      await screen.findByText("must be greater than stock.slow_threshold_days"),
    ).toBeInTheDocument();
    expect(seen.body).toEqual({
      settings: { "stock.dead_stock_days": 60, "reconciliation.money_absolute_tolerance": "2.50" },
    });
  });

  it("refuses a whole-number setting that is not one, before sending", async () => {
    serveCompanies(company());
    settingsApi();
    const seen = captureSettings();
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Thresholds" }));
    const window = await screen.findByLabelText(/^Look back/);
    await user.clear(window);
    await user.type(window, "1.5");
    await user.click(screen.getByRole("button", { name: "Save thresholds" }));
    expect(screen.getByText("must be a whole number")).toBeInTheDocument();
    expect(seen.body).toBeNull();
  });

  it("downloads the UDF TDL with the signed-in user's token", async () => {
    serveCompanies(admin());
    settingsApi();
    serve("/settings/custom-fields", []);
    let auth: string | null = null;
    server.use(
      http.get("*/api/companies/c-1/settings/custom-fields/tdl", ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.text("[#Collection: X]");
      }),
    );
    const clicked: string[] = [];
    URL.createObjectURL = () => "blob:udf";
    URL.revokeObjectURL = () => undefined;
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    };
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Custom fields" }));
    await user.click(await screen.findByRole("button", { name: "Download UDF TDL" }));
    await expect.poll(() => clicked).toEqual(["TallyAnalytics_UDF.tdl"]);
    expect(auth).toBe("Bearer test-token");
  });
});

describe("Users (RBAC-1.2)", () => {
  const owner = {
    user_id: "u-1",
    email: "owner@example.com",
    name: "Owner",
    is_active: true,
    roles: ["OWNER"],
  };

  it("says the initial password works once, and shows the last-Owner refusal", async () => {
    serveCompanies(company());
    serve("/users", [owner]);
    server.use(
      http.put("*/api/companies/c-1/users/u-1", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "A company must keep at least one Owner" },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/users");
    expect(
      await screen.findByText(/It works once: at first sign-in they must choose their own/),
    ).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Change" }));
    const row = screen.getByRole("row", { name: /owner@example.com/ });
    await user.click(within(row).getByRole("checkbox", { name: "OWNER" }));
    await user.click(within(row).getByRole("checkbox", { name: "ADMIN" }));
    await user.click(within(row).getByRole("button", { name: "Save roles" }));
    expect(await screen.findByText("A company must keep at least one Owner")).toBeInTheDocument();
  });

  it("adds a user with the roles chosen", async () => {
    serveCompanies(company());
    serve("/users", [owner]);
    let sent: unknown = null;
    server.use(
      http.post("*/api/companies/c-1/users", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/users");
    await user.type(await screen.findByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Name"), "New");
    await user.type(screen.getByLabelText(/^Initial password/), "initial-pass");
    await user.click(screen.getByRole("button", { name: "Add user" }));
    await screen.findByText("Added.");
    expect(sent).toEqual({
      email: "new@example.com",
      name: "New",
      password: "initial-pass",
      roles: ["ACCOUNTANT"],
    });
  });

  it("is not in an Admin's navigation", async () => {
    serveCompanies(admin());
    renderApp("/c/c-1/users");
    expect(
      await screen.findByRole("heading", { name: "Not available to you" }),
    ).toBeInTheDocument();
  });
});

describe("turning anomaly detection on (D-055 #7)", () => {
  const disclosure: Schemas["DisclosureOut"] = {
    model: "claude-sonnet-5-5",
    api_key_configured: true,
    fields_sent: ["rule", "currency", "party", "voucher", "transaction_amount"],
    example: {
      rule: "unusually large for this party compared with its recent history",
      currency: "INR",
      party: "Party A",
      voucher: "Voucher A",
      transaction_amount: "450000.0000",
    },
    system_prompt: "Use only the figures the tool returned. Never calculate a new number.",
    never_sent: ["party, ledger and company names", "narration", "dates"],
  };

  it("shows exactly what will be sent and needs the word typed", async () => {
    serveCompanies(admin());
    settingsApi();
    serve("/anomalies/disclosure", disclosure);
    let sent: unknown = null;
    server.use(
      http.put("*/api/companies/c-1/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ settings: {}, feature_flags: {} });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Feature flags" }));
    await user.click(await screen.findByRole("checkbox", { name: /Anomaly detection/ }));

    const dialog = await screen.findByRole("dialog", { name: "Turn on anomaly detection" });
    // The payload the server says it will send, and the placeholders rather than real names.
    expect(dialog).toHaveTextContent("Party A");
    expect(dialog).toHaveTextContent("Voucher A");
    expect(dialog).toHaveTextContent("claude-sonnet-5-5");
    expect(dialog).toHaveTextContent("narration");
    // Nothing is saved until ENABLE is typed.
    const confirm = within(dialog).getByRole("button", { name: "Turn it on" });
    expect(confirm).toBeDisabled();
    expect(sent).toBeNull();

    await user.type(within(dialog).getByRole("textbox"), "ENABLE");
    await user.click(confirm);
    await expect.poll(() => sent).toEqual({ feature_flags: { FEATURE_ANOMALY_DETECTION: true } });
  });

  it("saves nothing if the dialog is cancelled", async () => {
    serveCompanies(admin());
    settingsApi();
    serve("/anomalies/disclosure", disclosure);
    let sent: unknown = null;
    server.use(
      http.put("*/api/companies/c-1/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ settings: {}, feature_flags: {} });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/settings");
    await user.click(await screen.findByRole("tab", { name: "Feature flags" }));
    await user.click(await screen.findByRole("checkbox", { name: /Anomaly detection/ }));
    const dialog = await screen.findByRole("dialog", { name: "Turn on anomaly detection" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(sent).toBeNull();
  });
});
