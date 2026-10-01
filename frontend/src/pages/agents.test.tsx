import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../lib/session";
import { accountant, admin, agent, company, serve, serveCompanies } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

const NO_SCHEDULE = "NO_ACTIVE_SCHEDULE: an Agent is ACTIVE but no schedule is active";
const INITIAL = "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet";

describe("Agents page (FR-4.4)", () => {
  it("shows every warning an Agent can carry", async () => {
    serveCompanies(company());
    serve("/agents", {
      warnings: [NO_SCHEDULE, INITIAL],
      agents: [
        agent({
          agent_name: "Head Office PC",
          uptime_advisory: "prominent",
          last_tally_status: "TALLY_UNREACHABLE",
          tally_status_since: "2026-03-16T03:30:00Z",
          warnings: [
            "COMPANY_MISMATCH: re-register this Agent (AGT-3.4)",
            "INCOMPATIBLE: upgrade the Agent or its TDL package",
            "QUEUE_FULL: the Agent's local queue is full",
          ],
          queue_status: { records: 5000, dead_letter_count: 3, full: true, oldest_age_seconds: 60 },
        }),
        agent({
          agent_id: "a-2",
          agent_name: "Godown PC",
          status: "OFFLINE",
          offline_since: "2026-03-15T18:30:00Z",
          uptime_advisory: "advisory",
          last_tally_status: "TDL_NOT_LOADED",
        }),
      ],
    });
    renderApp("/c/c-1/agents");
    expect(await screen.findByText(NO_SCHEDULE)).toBeInTheDocument();
    expect(screen.getByText(INITIAL)).toBeInTheDocument();
    const [first, second] = screen.getAllByRole("listitem").filter((li) => li.querySelector("h2"));
    if (!first || !second) throw new Error("two Agents expected");
    const one = within(first);
    expect(one.getByText(/latest reconciliation failed/)).toHaveTextContent("Restart recommended");
    expect(one.getByText(/^Tally not running/)).toHaveTextContent("since 16 Mar 2026, 09:00");
    expect(one.getByText(/COMPANY_MISMATCH/)).toBeInTheDocument();
    expect(one.getByText(/INCOMPATIBLE: upgrade/)).toBeInTheDocument();
    expect(one.getByText(/QUEUE_FULL/)).toBeInTheDocument();
    expect(one.getByText("5000 waiting · 3 failed · FULL")).toBeInTheDocument();
    const two = within(second);
    expect(two.getByText("OFFLINE")).toBeInTheDocument();
    expect(second).toHaveTextContent("offline since 16 Mar 2026, 00:00");
    expect(
      two.getByText("Restart recommended: Tally has been running for a long time."),
    ).toBeInTheDocument();
    expect(two.getByText(/TDL is not loaded/)).toBeInTheDocument();
  });

  it("offers no Agent actions to an Accountant", async () => {
    serveCompanies(accountant());
    serve("/agents", { warnings: [], agents: [agent()] });
    renderApp("/c/c-1/agents");
    expect(await screen.findByText("Head Office PC")).toBeInTheDocument();
    for (const name of ["Register a new Agent", "Tally settings", "Rotate credential", "Revoke"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("shows a registration token once, with its expiry in company time", async () => {
    serveCompanies(admin());
    serve("/agents", { warnings: [], agents: [] });
    server.use(
      http.post("*/api/companies/c-1/agents/register-token", () =>
        HttpResponse.json(
          { token: "reg-secret-123", expires_at: "2026-03-17T06:30:00Z" },
          { status: 201 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/agents");
    await user.click(await screen.findByRole("button", { name: "Register a new Agent" }));
    const dialog = await screen.findByRole("dialog", { name: "Registration token" });
    expect(within(dialog).getByText("reg-secret-123")).toBeInTheDocument();
    expect(dialog).toHaveTextContent("expires 17 Mar 2026, 12:00");
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.queryByText("reg-secret-123")).not.toBeInTheDocument();
  });

  it("revokes only after the word is typed", async () => {
    serveCompanies(admin());
    serve("/agents", { warnings: [], agents: [agent()] });
    let revoked = 0;
    server.use(
      http.post("*/api/companies/c-1/agents/a-1/revoke", () => {
        revoked += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/agents");
    await user.click(await screen.findByRole("button", { name: "Revoke" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Revoke" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox"), "REVOKE");
    await user.click(confirm);
    await screen.findByRole("button", { name: "Revoke" });
    expect(revoked).toBe(1);
  });

  it("refuses a batch size above 10,000 before sending it", async () => {
    serveCompanies(admin());
    serve("/agents", { warnings: [], agents: [agent()] });
    let sent = 0;
    server.use(
      http.put("*/api/companies/c-1/agents/a-1/tally-settings", () => {
        sent += 1;
        return HttpResponse.json({ warnings: [], agents: [agent()] });
      }),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/agents");
    await user.click(await screen.findByRole("button", { name: "Tally settings" }));
    await user.type(screen.getByLabelText(/^Batch size/), "10001");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("from 1 to 10,000");
    expect(sent).toBe(0);
    await user.clear(screen.getByLabelText(/^Batch size/));
    await user.type(screen.getByLabelText(/^Batch size/), "500");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("button", { name: "Tally settings" });
    expect(sent).toBe(1);
  });
});
