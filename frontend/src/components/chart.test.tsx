import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { toChartNumber } from "../lib/chartNumber";
import { formatMoney } from "../lib/format";
import { Chart, ChartTip } from "./Chart";

// 17 digits before the point: a float keeps only ~16 significant digits, so a figure drawn
// through Number() would read ₹12,34,56,78,90,12,34,568.00, not the backend's amount.
const BIG = "12345678901234567.89";
const POINTS = [
  { key: "2025-04-01", label: "Apr 2025", amount: BIG },
  { key: "2025-05-01", label: "May 2025", amount: "-1250.50" },
];

describe("charts show the backend's figures (D-053 #5)", () => {
  it("draw every bar, and show only the backend's labels as text", () => {
    const { container } = render(<Chart title="Sales by month" points={POINTS} />);
    expect(container.querySelectorAll(".recharts-bar-rectangle")).toHaveLength(2);
    const texts = [...container.querySelectorAll("svg text")].map((t) => t.textContent);
    expect(texts.length).toBeGreaterThan(0);
    for (const text of texts) expect(["Apr 2025", "May 2025"]).toContain(text);
  });

  it("show a tapped bar's amount exactly as the backend sent it, with a way to its vouchers", async () => {
    const onSelect = vi.fn();
    render(
      <ChartTip
        point={{ key: "2025-04-01", label: "Apr 2025", amount: BIG }}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText("₹12,34,56,78,90,12,34,567.89")).toBeInTheDocument();
    expect(formatMoney(String(toChartNumber(BIG)))).not.toBe(formatMoney(BIG)); // the trap
    await userEvent.click(screen.getByRole("button", { name: "See vouchers" }));
    expect(onSelect).toHaveBeenCalledWith("2025-04-01");
  });

  it("size bars from valid decimal strings only", () => {
    expect(toChartNumber("-1250.50")).toBe(-1250.5);
    for (const bad of ["", "₹1", "1,000", "abc", "NaN", "Infinity", "1.2.3"]) {
      expect(() => toChartNumber(bad)).toThrow("not a decimal amount");
    }
  });
});
