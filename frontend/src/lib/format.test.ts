import { describe, expect, it } from "vitest";
import { formatDate, formatMoney, formatTimestamp } from "./format";

describe("formatMoney (D-051 #5: our own function, no float, no Intl)", () => {
  it.each([
    ["12345678.9000", "₹1,23,45,678.90"],
    ["100000", "₹1,00,000.00"],
    ["1.005", "₹1.01"], // a float would give 1.00
    ["-1.005", "-₹1.01"],
    ["999.995", "₹1,000.00"],
    ["0", "₹0.00"],
    ["-0.004", "₹0.00"], // never "-₹0.00"
    ["12.3", "₹12.30"],
    ["-2500.5", "-₹2,500.50"],
    ["1E+2", "₹100.00"],
    ["0.0000", "₹0.00"],
    ["  42  ", "₹42.00"],
    // 25 digits: far beyond a float's 15-17
    ["1234567890123456789012345.678", "₹12,34,56,78,90,12,34,56,78,90,12,345.68"],
  ])("%s -> %s", (value, shown) => {
    expect(formatMoney(value)).toBe(shown);
  });

  it("never touches a float: 0.1 + 0.2 stays exact", () => {
    expect(formatMoney("0.30000000000000004")).toBe("₹0.30");
    expect(formatMoney("9007199254740993.00")).toBe("₹9,00,71,99,25,47,40,993.00"); // 2^53 + 1
  });

  it.each(["", "abc", "1.2.3", "₹100", "1,000"])("refuses %j", (value) => {
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
