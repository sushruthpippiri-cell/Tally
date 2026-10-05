import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { setAccessToken } from "../lib/session";
import { accountant, admin, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

function anomaly(extra: Partial<Schemas["AnomalyOut"]> = {}): Schemas["AnomalyOut"] {
  return {
    anomaly_id: 1,
    rule: "UNUSUALLY_LARGE_SD",
    rule_label: "unusually large for this party compared with its recent history",
    voucher_id: "v-1",
    voucher_date: "2026-03-02",
    voucher_number: "SI/41",
    party_name: "Mehta Electricals",
    duplicate_of_voucher_id: null,
    duplicate_of_voucher_number: null,
    duplicate_of_voucher_date: null,
    transaction_amount: "450000.0000",
    historical_average: "70000.0000",
    historical_max: "120000.0000",
    deviation_percent: "542.857143",
    deviation_display: "+543%",
    flagged_at: "2026-03-16T06:30:00Z",
    explanation_status: "AVAILABLE",
    explanation_text: "Mehta Electricals was invoiced ₹4,50,000, well above its usual amounts.",
    explanation_unavailable_reason: null,
    reviewed: false,
    not_an_issue: false,
    reviewed_at: null,
    ...extra,
  };
}

function listing(extra: Partial<Schemas["AnomaliesOut"]> = {}): Schemas["AnomaliesOut"] {
  return {
    available: true,
    reason: null,
    company_timezone: "Asia/Kolkata",
    anomalies: [anomaly()],
    total_count: 1,
    ...extra,
  };
}

const enabled = () => company({ anomaly_detection_enabled: true });

describe("the Anomalies section (SRS 12)", () => {
  it("is not listed at all while the feature flag is off (FR-3.1)", async () => {
    serveCompanies(company()); // anomaly_detection_enabled: false
    serve("/analytics/sales", {
      metric: "sales",
      filters_applied: {
        date_from: "2025-04-01",
        date_to: "2026-03-16",
        granularity: "month",
        group_by: "ledger",
        include_cancelled: false,
        include_missing: false,
        by: [],
        not_applicable: [],
      },
      company_timezone: "Asia/Kolkata",
      summary: { amount: "1", available: true, unavailable_count: 0, unavailable_ledgers: [] },
      series: [],
      breakdown: [],
      notes: [],
    });
    renderApp("/c/c-1/sales");
    const [nav] = await screen.findAllByRole("navigation", { name: "Sections" });
    expect(nav).toBeDefined();
    expect(
      within(nav as HTMLElement).queryByRole("link", { name: "Anomalies" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the evidence and the explanation in separate labelled areas (FR-3.7)", async () => {
    serveCompanies(enabled());
    serve("/anomalies", listing());
    const user = userEvent.setup();
    renderApp("/c/c-1/anomalies");
    await user.click(await screen.findByRole("button", { name: "Details" }));

    const evidence = screen.getByRole("region", { name: "Evidence" });
    const explanation = screen.getByRole("region", { name: "Explanation" });
    // Every figure is in the evidence panel, measured by this system.
    expect(within(evidence).getByText("₹4,50,000.00")).toBeInTheDocument();
    expect(within(evidence).getByText("₹70,000.00")).toBeInTheDocument();
    expect(within(evidence).getByText("₹1,20,000.00")).toBeInTheDocument();
    expect(within(evidence).getByText("+543%")).toBeInTheDocument();
    // The explanation is Claude's, and says so.
    expect(explanation).toHaveTextContent("written by Claude");
    expect(explanation).toHaveTextContent("well above its usual amounts");
  });

  it("says why an explanation is missing, and still shows the evidence (AC-58)", async () => {
    serveCompanies(enabled());
    serve(
      "/anomalies",
      listing({
        anomalies: [
          anomaly({
            explanation_status: "UNAVAILABLE",
            explanation_text: null,
            explanation_unavailable_reason: "CLAUDE_UNREACHABLE",
          }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/anomalies");
    await user.click(await screen.findByRole("button", { name: "Details" }));
    expect(screen.getByRole("region", { name: "Evidence" })).toHaveTextContent("₹4,50,000.00");
    expect(screen.getByRole("region", { name: "Explanation" })).toHaveTextContent(
      /could not be reached/i,
    );
  });

  it("explains a discarded explanation plainly (FR-3.6)", async () => {
    serveCompanies(enabled());
    serve(
      "/anomalies",
      listing({
        anomalies: [
          anomaly({
            explanation_status: "UNAVAILABLE",
            explanation_text: null,
            explanation_unavailable_reason: "NUMBER_NOT_IN_EVIDENCE",
          }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/anomalies");
    await user.click(await screen.findByRole("button", { name: "Details" }));
    expect(screen.getByRole("region", { name: "Explanation" })).toHaveTextContent(
      /figure that is not in the evidence/i,
    );
  });

  it("renders a hostile explanation as text, never as markup", async () => {
    serveCompanies(enabled());
    const nasty = '<img src=x onerror="alert(1)"> <script>alert(2)</script>';
    serve("/anomalies", listing({ anomalies: [anomaly({ explanation_text: nasty })] }));
    const user = userEvent.setup();
    renderApp("/c/c-1/anomalies");
    await user.click(await screen.findByRole("button", { name: "Details" }));
    const explanation = screen.getByRole("region", { name: "Explanation" });
    expect(explanation).toHaveTextContent("<script>alert(2)</script>");
    expect(explanation.querySelector("script")).toBeNull();
    expect(explanation.querySelector("img")).toBeNull();
  });

  it("lets an Accountant review but not an Admin (SRS 14.1)", async () => {
    for (const [who, canReview] of [
      [accountant(), true],
      [admin(), false],
    ] as const) {
      serveCompanies({ ...who, anomaly_detection_enabled: true });
      serve("/anomalies", listing());
      const user = userEvent.setup();
      const view = renderApp("/c/c-1/anomalies");
      await user.click(await screen.findByRole("button", { name: "Details" }));
      const button = screen.queryByRole("button", { name: "Mark reviewed" });
      if (canReview) expect(button).toBeInTheDocument();
      else expect(button).not.toBeInTheDocument();
      view.unmount();
      server.resetHandlers();
    }
  });

  it("posts the review action and shows the new status", async () => {
    serveCompanies(enabled());
    serve("/anomalies", listing());
    let sent: unknown = null;
    server.use(
      http.post("*/api/companies/c-1/anomalies/1/review", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(anomaly({ reviewed: true, not_an_issue: true }));
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/anomalies");
    await user.click(await screen.findByRole("button", { name: "Details" }));
    await user.click(screen.getByRole("button", { name: "Not an issue" }));
    await expect.poll(() => sent).toEqual({ action: "not_an_issue" });
    // The panel reflects the answer the server gave: nothing left to review on this one.
    const detail = await screen.findByRole("region", { name: "Anomaly detail" });
    await expect
      .poll(() => within(detail).queryByRole("button", { name: "Mark reviewed" }))
      .toBeNull();
    expect(within(detail).queryByRole("button", { name: "Not an issue" })).toBeNull();
  });

  it("shows the disabled message if the page is opened directly", async () => {
    serveCompanies(enabled());
    serve("/anomalies", {
      available: false,
      reason: "Anomaly detection is off for this company.",
      company_timezone: "Asia/Kolkata",
      anomalies: [],
      total_count: 0,
    });
    renderApp("/c/c-1/anomalies");
    expect(await screen.findByText(/off for this company/)).toBeInTheDocument();
  });
});
