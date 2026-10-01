import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import type { Schemas } from "../api/types";
import { setAccessToken } from "../lib/session";
import { accountant, admin, agent, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const INITIAL = "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet";

function collection(
  overrides: Partial<Schemas["CollectionStatus"]> = {},
): Schemas["CollectionStatus"] {
  return {
    collection_type: "VOUCHER",
    mode: "INCREMENTAL",
    label: "Incremental",
    watermark: 120,
    status: "OK",
    last_successful_sync_at: "2026-03-16T06:30:00Z",
    lease_holder: null,
    lease_expires_at: null,
    held_back: 0,
    ...overrides,
  };
}

function command(
  overrides: Partial<Schemas["CommandStatusOut"]> = {},
): Schemas["CommandStatusOut"] {
  return {
    command_id: "cmd-1",
    agent_id: "a-1",
    agent_name: "Head Office PC",
    sync_mode: "INCREMENTAL",
    date_from: null,
    date_to: null,
    status: "PENDING",
    created_at: "2026-03-16T06:30:00Z",
    created_by: null,
    claimed_at: null,
    lease_expires_at: null,
    completed_at: null,
    error_code: null,
    error_message: null,
    waiting_label: null,
    ...overrides,
  };
}

function syncApi({ agents = [agent()] }: { agents?: Schemas["AgentOut"][] } = {}) {
  serve("/agents", { warnings: [], agents });
  serve("/sync/status", {
    warnings: [INITIAL],
    last_run: {
      sync_run_id: "r-1",
      status: "PARTIAL",
      records_fetched: 900,
      records_failed: 3,
      started_at: "2026-03-16T05:30:00Z",
      ended_at: "2026-03-16T05:40:00Z",
      agent_id: "a-1",
      command_id: null,
      sync_mode: "INCREMENTAL",
    },
    reconciliation: null,
    collections: [
      collection({ collection_type: "LEDGER", mode: "FULL_ONLY", label: "Full sync only" }),
      collection({
        held_back: 3,
        lease_holder: "Head Office PC",
        lease_expires_at: "2026-03-16T06:40:00Z",
      }),
    ],
  });
  serve("/sync/runs", [
    {
      sync_run_id: "r-1",
      status: "FAILED",
      records_fetched: 0,
      records_failed: 0,
      started_at: "2026-03-16T05:30:00Z",
      ended_at: null,
      agent_id: "a-1",
      command_id: null,
      sync_mode: "FULL",
    },
  ]);
  serve("/sync/errors", []);
  serve("/sync-schedules", []);
}

describe("Sync page", () => {
  it("shows every sync warning: initial sync, full-only, held back, failed runs, lease", async () => {
    serveCompanies(company());
    syncApi();
    renderApp("/c/c-1/sync");
    expect(await screen.findByText(INITIAL)).toBeInTheDocument();
    expect(screen.getByText("Full sync only")).toBeInTheDocument();
    expect(screen.getByText("Held back by 3 failing records")).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(await screen.findByText("FAILED")).toBeInTheDocument();
    const lease = screen.getByText(
      (_, el) => el?.tagName === "TD" && /^Head Office PC until/.test(el.textContent ?? ""),
    );
    expect(lease).toHaveTextContent("Head Office PC until 16 Mar 2026, 12:10");
  });

  it("does not send Sync Now with two ACTIVE Agents until one is chosen (AC-18 UI)", async () => {
    serveCompanies(company());
    syncApi({ agents: [agent(), agent({ agent_id: "a-2", agent_name: "Godown PC" })] });
    const sent: unknown[] = [];
    server.use(
      http.post("*/api/companies/c-1/sync", async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(command({ agent_id: "a-2", agent_name: "Godown PC" }), {
          status: 201,
        });
      }),
      http.get("*/api/companies/c-1/commands/cmd-1", () => HttpResponse.json(command())),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/sync");
    const form = await screen.findByRole("form", { name: "Sync now" });
    const select = await within(form).findByLabelText("Agent");
    expect(select).toBeRequired();
    await user.click(screen.getByRole("button", { name: "Sync Now" }));
    expect(select).toBeInvalid(); // the browser will not submit the form (AC-18)
    expect(sent).toEqual([]);
    await user.selectOptions(select, "a-2");
    await user.click(screen.getByRole("button", { name: "Sync Now" }));
    expect(await screen.findByRole("list", { name: "Sync progress" })).toBeInTheDocument();
    expect(sent).toEqual([
      { sync_mode: "INCREMENTAL", agent_id: "a-2", date_from: null, date_to: null },
    ]);
  });

  it("asks for an Agent when the API says one must be chosen", async () => {
    serveCompanies(company());
    syncApi({ agents: [agent()] });
    server.use(
      http.post("*/api/companies/c-1/sync", () =>
        HttpResponse.json(
          { code: "AGENT_SELECTION_REQUIRED", message: "choose one" },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/sync");
    await user.click(await screen.findByRole("button", { name: "Sync Now" }));
    const form = screen.getByRole("form", { name: "Sync now" });
    expect(await within(form).findByLabelText("Agent")).toBeRequired();
  });

  it("labels a command waiting for an offline Agent (AC-19 UI)", async () => {
    serveCompanies(company());
    syncApi();
    const waiting = "Waiting — Agent offline since 16 Mar 2026, 10:00";
    server.use(
      http.post("*/api/companies/c-1/sync", () => HttpResponse.json(command(), { status: 201 })),
      http.get("*/api/companies/c-1/commands/cmd-1", () =>
        HttpResponse.json(command({ waiting_label: waiting })),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/sync");
    await user.click(await screen.findByRole("button", { name: "Sync Now" }));
    expect(await screen.findByText(waiting)).toBeInTheDocument();
  });

  it("shows how a finished command ended, with its error in plain words", async () => {
    serveCompanies(company());
    syncApi();
    server.use(
      http.post("*/api/companies/c-1/sync", () => HttpResponse.json(command(), { status: 201 })),
      http.get("*/api/companies/c-1/commands/cmd-1", () =>
        HttpResponse.json(
          command({
            status: "FAILED",
            claimed_at: "2026-03-16T06:31:00Z",
            completed_at: "2026-03-16T06:35:00Z",
            error_code: "TDL_NOT_LOADED",
            error_message: "Unknown report",
          }),
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/sync");
    await user.click(await screen.findByRole("button", { name: "Sync Now" }));
    const steps = await screen.findByRole("list", { name: "Sync progress" });
    expect(
      within(steps)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "PENDING16 Mar 2026, 12:00",
      "CLAIMED16 Mar 2026, 12:01",
      "RUNNING",
      "FAILED16 Mar 2026, 12:05",
    ]);
    expect(screen.getByText(/TDL is not loaded/)).toHaveTextContent("(Unknown report)");
  });

  it("shows schedules and errors to an Admin, not to an Accountant", async () => {
    serveCompanies(admin());
    syncApi();
    renderApp("/c/c-1/sync");
    expect(await screen.findByRole("heading", { name: "Schedules" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sync errors" })).toBeInTheDocument();
  });

  it("hides schedules and errors from an Accountant", async () => {
    serveCompanies(accountant());
    syncApi();
    renderApp("/c/c-1/sync");
    expect(await screen.findByRole("heading", { name: "Recent runs" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Schedules" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sync errors" })).not.toBeInTheDocument();
  });

  it("previews a schedule in words and company time, and sends it", async () => {
    serveCompanies(company());
    syncApi();
    let sent: unknown = null;
    server.use(
      http.post("*/api/companies/c-1/sync-schedules", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/sync");
    const cron = await screen.findByLabelText(/^Cron expression/);
    await user.clear(cron);
    await user.type(cron, "30 9 * * 1");
    expect(screen.getByText("Mondays at 09:30 (company time, Asia/Kolkata)")).toBeInTheDocument();
    const form = cron.closest("form");
    if (!form) throw new Error("no form");
    await user.selectOptions(within(form).getByLabelText("Agent"), "a-1");
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    await screen.findByRole("button", { name: "Add schedule" });
    expect(sent).toEqual({
      agent_id: "a-1",
      cron_expression: "30 9 * * 1",
      sync_mode: "INCREMENTAL",
      is_active: true,
    });
  });
});
