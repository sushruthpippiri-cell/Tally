import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import openapi from "../api/openapi.json";
import { MESSAGES, messageFor } from "./errorMessages";

describe("the error catalogue (P13.5)", () => {
  it("has a message for every ErrorCode the API can send", () => {
    const codes = (openapi.components.schemas.ErrorCode as { enum: string[] }).enum;
    expect(Object.keys(MESSAGES).sort()).toEqual([...codes].sort());
    for (const code of codes) {
      const text = messageFor(new ApiError(400, code as never, "server text"));
      expect(text, code).toMatch(/\S/);
    }
  });

  it("uses SRS 16's wording for the Tally failures", () => {
    expect(messageFor(new ApiError(503, "TALLY_UNREACHABLE", "x"))).toMatch(
      /^Tally not running — the Windows user may have logged off/,
    );
    expect(messageFor(new ApiError(409, "AGENT_INCOMPATIBLE", "x"))).toMatch(
      /^Agent update required/,
    );
  });

  it("names the Agent holding a lease", () => {
    const locked = new ApiError(409, "SYNC_LOCKED", "x", { holder: "Head Office" });
    expect(messageFor(locked)).toBe(
      "Sync in progress by Head Office. It will continue once that finishes.",
    );
  });

  it("shows the server's own words where they are specific", () => {
    const invalid = new ApiError(422, "VALIDATION_ERROR", "period_days must be 30, 60, 90 or 180");
    expect(messageFor(invalid)).toBe("period_days must be 30, 60, 90 or 180");
  });

  it("has a message for a network failure", () => {
    expect(messageFor(new ApiError(0, "NETWORK_ERROR", ""))).toMatch(/could not be reached/);
  });
});
