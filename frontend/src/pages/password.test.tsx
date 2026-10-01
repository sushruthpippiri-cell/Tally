import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { getMustChangePassword, setAccessToken } from "../lib/session";
import { resetRestore } from "../lib/useSession";
import { ACCOUNTANT, company } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server, withMockApi } from "../test/server";

withMockApi();
afterEach(() => {
  setAccessToken(null);
  resetRestore();
});

const accountant = company({ my_roles: ["ACCOUNTANT"], my_permissions: ACCOUNTANT });

function companiesApi(seen: string[] = []) {
  server.use(
    http.get("*/api/companies", () => {
      seen.push("companies");
      return HttpResponse.json([accountant, company({ company_id: "c-2" })]);
    }),
    http.get("*/api/companies/c-1", () => HttpResponse.json(accountant)),
  );
  return seen;
}

describe("first sign-in with an initial password (D-052)", () => {
  it("goes to Choose your password and nowhere else until it is changed", async () => {
    const seen = companiesApi();
    let sent: unknown = null;
    server.use(
      http.post("*/api/auth/refresh", () => new HttpResponse(null, { status: 401 })),
      http.post("*/api/auth/login", () =>
        HttpResponse.json({ access_token: "a1", expires_in: 1800, must_change_password: true }),
      ),
      http.post("*/api/auth/change-password", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          access_token: "a2",
          expires_in: 1800,
          must_change_password: false,
        });
      }),
    );
    const user = userEvent.setup();
    renderApp("/login", { signedIn: false });
    await user.type(await screen.findByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "initial-pass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "Choose your password" }),
    ).toBeInTheDocument();
    expect(seen).toEqual([]); // no company page was even asked for

    await user.type(screen.getByLabelText("Password you were given"), "initial-pass");
    await user.type(screen.getByLabelText(/^New password \(/), "my-own-password");
    await user.type(screen.getByLabelText("New password again"), "my-own-password");
    await user.click(screen.getByRole("button", { name: "Save password" }));

    expect(await screen.findByRole("heading", { name: "Companies" })).toBeInTheDocument();
    expect(sent).toEqual({ current_password: "initial-pass", new_password: "my-own-password" });
    expect(getMustChangePassword()).toBe(false);
  });

  it("sends the user there when the API refuses with PASSWORD_CHANGE_REQUIRED", async () => {
    server.use(
      http.get("*/api/companies", () =>
        HttpResponse.json(
          { code: "PASSWORD_CHANGE_REQUIRED", message: "Choose a new password" },
          { status: 403 },
        ),
      ),
    );
    renderApp("/companies");
    expect(
      await screen.findByRole("heading", { name: "Choose your password" }),
    ).toBeInTheDocument();
  });

  it("refuses two different new passwords before sending anything", async () => {
    setAccessToken("t", true);
    const user = userEvent.setup();
    renderApp("/account/password", { signedIn: false });
    await user.type(await screen.findByLabelText("Password you were given"), "initial-pass");
    await user.type(screen.getByLabelText(/^New password \(/), "my-own-password");
    await user.type(screen.getByLabelText("New password again"), "my-own-passw0rd");
    await user.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not the same");
  });
});

describe("change password, for every role (SEC-1.1)", () => {
  it("is linked from the company shell for an Accountant and keeps them signed in", async () => {
    companiesApi();
    server.use(
      http.post("*/api/auth/change-password", () =>
        HttpResponse.json({ access_token: "a3", expires_in: 1800, must_change_password: false }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/c/c-1/home");
    const [link] = await screen.findAllByRole("link", { name: "Change password" });
    if (!link) throw new Error("no Change password link");
    await user.click(link);
    expect(await screen.findByRole("heading", { name: "Change password" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Current password"), "old-password");
    await user.type(screen.getByLabelText(/^New password \(/), "new-password");
    await user.type(screen.getByLabelText("New password again"), "new-password");
    await user.click(screen.getByRole("button", { name: "Save password" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Password changed"));
  });

  it("shows the API's refusal of a wrong current password", async () => {
    server.use(
      http.post("*/api/auth/change-password", () =>
        HttpResponse.json(
          { code: "FORBIDDEN", message: "Current password is incorrect" },
          { status: 403 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/account/password");
    await user.type(await screen.findByLabelText("Current password"), "wrong-password");
    await user.type(screen.getByLabelText(/^New password \(/), "new-password");
    await user.type(screen.getByLabelText("New password again"), "new-password");
    await user.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
