import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../lib/session";
import { ACCOUNTANT, company } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => setAccessToken(null));

function companies(...list: ReturnType<typeof company>[]) {
  server.use(
    http.get("*/api/companies", () => HttpResponse.json(list)),
    ...list.map((c) => http.get(`*/api/companies/${c.company_id}`, () => HttpResponse.json(c))),
  );
}

async function sections(): Promise<string[]> {
  const nav = (await screen.findAllByRole("navigation", { name: "Sections" }))[0];
  if (!nav) throw new Error("no navigation");
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");
}

describe("companies (P13.4)", () => {
  it("goes straight into the only company", async () => {
    companies(company());
    renderApp("/companies");
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
  });

  it("lists several companies with the user's roles", async () => {
    companies(
      company(),
      company({ company_id: "c-2", name: "Gupta Stores", my_roles: ["ACCOUNTANT"] }),
    );
    renderApp("/companies");
    expect(await screen.findByRole("link", { name: /Gupta Stores/ })).toHaveAttribute(
      "href",
      "/c/c-2/home",
    );
    expect(screen.getByText(/ACCOUNTANT · Asia\/Kolkata/)).toBeInTheDocument();
  });
});

describe("role-aware navigation (RBAC-1.1, UI side)", () => {
  it("shows an Owner every section", async () => {
    companies(company());
    renderApp("/c/c-1/home");
    expect(await sections()).toEqual([
      "Home",
      "Sync",
      "Agents",
      "Reconciliation",
      "Data Quality",
      "Settings",
      "Users",
    ]);
  });

  it("hides Settings and Users from an Accountant", async () => {
    companies(company({ my_roles: ["ACCOUNTANT"], my_permissions: ACCOUNTANT }));
    renderApp("/c/c-1/home");
    expect(await sections()).toEqual(["Home", "Sync", "Agents", "Reconciliation", "Data Quality"]);
  });

  it("shows Forbidden when an Accountant opens Settings directly", async () => {
    companies(company({ my_roles: ["ACCOUNTANT"], my_permissions: ACCOUNTANT }));
    renderApp("/c/c-1/settings");
    expect(
      await screen.findByRole("heading", { name: "Not available to you" }),
    ).toBeInTheDocument();
  });

  it("shows Forbidden for a company the API refuses", async () => {
    server.use(
      http.get("*/api/companies/c-9", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "Not permitted" }, { status: 403 }),
      ),
    );
    renderApp("/c/c-9/home");
    expect(
      await screen.findByRole("heading", { name: "Not available to you" }),
    ).toBeInTheDocument();
  });
});
