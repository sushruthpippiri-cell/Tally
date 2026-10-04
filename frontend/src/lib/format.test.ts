import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { formatDate, formatMoney, formatTimestamp } from "./format";

/** The same cases backend/tests/exports/test_money.py asserts, so this function and
 * app/exports/money.py cannot drift (D-053 #6, #7). The `csv` column is the backend's. */
const fixture = JSON.parse(
  readFileSync("../fixtures/money-formatting.json", "utf-8"), // Vitest runs with root = frontend/
) as { cases: { value: string; money: string; csv: string }[]; refused: string[] };

describe("formatMoney (D-051 #5: our own function, no float, no Intl)", () => {
  it.each(fixture.cases.map((c) => [c.value, c.money]))("%s -> %s", (value, shown) => {
    expect(formatMoney(value as string)).toBe(shown);
  });

  it("covers the 25-digit and 2^53 + 1 cases, far beyond a float", () => {
    const values = fixture.cases.map((c) => c.value);
    expect(values).toContain("1234567890123456789012345.678");
    expect(values).toContain("9007199254740993.00");
    expect(values).toContain("0.30000000000000004");
  });

  it.each(fixture.refused)("refuses %j", (value) => {
    expect(() => formatMoney(value)).toThrow("not a decimal amount");
  });
});

describe("dates in the company's time zone (TZ-1.1), in a Los Angeles browser", () => {
  it("runs where the browser is far from India", () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe("America/Los_Angeles");
  });

  it("formats a DATE from its parts, never shifting it", () => {
    expect(formatDate("2026-03-16")).toBe("16 Mar 2026");
    expect(formatDate("2026-01-01")).toBe("01 Jan 2026");
  });

  it("shows a timestamp on the company's day, not the browser's", () => {
    // 18:30 UTC on 31 March is midnight on 1 April in India, 11:30 on 31 March in Los Angeles.
    expect(formatTimestamp("2026-03-31T18:30:00Z", "Asia/Kolkata")).toBe("01 Apr 2026, 00:00");
    expect(formatTimestamp("2026-03-31T18:29:59Z", "Asia/Kolkata")).toBe("31 Mar 2026, 23:59");
  });
});
