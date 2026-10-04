import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../lib/session";
import { agent, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const INITIAL = "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet";
const NO_SCHEDULE = "NO_ACTIVE_SCHEDULE: an Agent is ACTIVE but no schedule is active";

describe("Home (P13.10)", () => {
  it("shows every warning from sync, reconciliation and Agents", async () => {
    serveCompanies(company());
    serve("/sync/status", {
      warnings: [INITIAL],
      collections: [],
      last_run: {
        sync_run_id: "r-1",
        status: "PARTIAL",
        records_fetched: 10,
        records_failed: 2,
        started_at: "2026-03-16T05:30:00Z",
        ended_at: "2026-03-16T05:40:00Z",
        agent_id: "a-1",
        command_id: null,
        sync_mode: "INCREMENTAL",
      },
      reconciliation: { sync_run_id: "r-1", run_at: "2026-03-16T06:00:00Z", overall: "FAIL" },
    });
    serve("/agents", {
      warnings: [NO_SCHEDULE],
      agents: [
        agent({
          uptime_advisory: "prominent",
          warnings: ["QUEUE_FULL: the Agent's local queue is full"],
        }),
        agent({
          agent_id: "a-2",
          agent_name: "Godown PC",
          status: "OFFLINE",
          uptime_advisory: "advisory",
        }),
      ],
    });
    renderApp("/c/c-1/home");
    expect(await screen.findByText(INITIAL)).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText("16 Mar 2026, 11:10")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText(/differ from Tally's beyond the tolerance/)).toBeInTheDocument();
    expect(await screen.findByText(NO_SCHEDULE)).toBeInTheDocument();
    expect(
      screen.getByText("Head Office PC: QUEUE_FULL: the Agent's local queue is full"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Restart recommended on Head Office PC: the latest reconciliation failed/),
    ).toBeInTheDocument();
    expect(screen.getByText("Restart recommended on Godown PC.")).toBeInTheDocument();
    expect(screen.getByText("1 ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("1 OFFLINE")).toBeInTheDocument();
  });
});
