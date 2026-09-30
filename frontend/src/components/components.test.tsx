import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Figure, Money } from "./Money";
import { ScrollableTable } from "./ScrollableTable";
import { ConfirmDialog, DateText, TimeText } from "./ui";
import { Warnings } from "./Warnings";

describe("Money and Figure", () => {
  it("shows the backend's string with Indian grouping", () => {
    render(<Money value="12345678.9000" />);
    expect(screen.getByText("₹1,23,45,678.90")).toBeInTheDocument();
  });

  it("shows a balance with Dr/Cr", () => {
    render(
      <Figure
        figure={{
          amount: "70000.0000",
          direction: "Dr",
          available: true,
          unavailable_count: 0,
          unavailable_ledgers: [],
        }}
      />,
    );
    expect(screen.getByText("₹70,000.00")).toHaveTextContent("₹70,000.00Dr");
  });

  it("never shows an unavailable balance as ₹0: it names the ledgers", () => {
    render(
      <Figure
        figure={{
          amount: null,
          available: false,
          unavailable_count: 3,
          unavailable_ledgers: ["HDFC Bank", "Loan"],
        }}
      />,
    );
    expect(screen.getByText(/Opening balance unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Missing for: HDFC Bank, Loan and 1 more")).toBeInTheDocument();
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument();
  });
});

describe("Warnings (D-051 #7)", () => {
  it("shows every kind at once, with nothing to dismiss or collapse", () => {
    render(
      <Warnings
        unverifiedGates={["G25", "G31"]}
        warnings={[
          "The newest stock snapshot is from 2026-03-10, 6 days ago",
          "INITIAL_SYNC_INCOMPLETE: no sync has completed without errors yet",
          "NO_ACTIVE_SCHEDULE: nothing is scheduled",
        ]}
        notes={["Only settlements on Receipt vouchers are payments"]}
        limitations={["Items sold in more than one unit are not converted"]}
      />,
    );
    const list = screen.getByRole("list", { name: "Warnings and notes" });
    for (const text of [
      /Awaiting Tally validation \(G25, G31\)/,
      /stock snapshot is from 2026-03-10/,
      /INITIAL_SYNC_INCOMPLETE/,
      /NO_ACTIVE_SCHEDULE/,
      /Receipt vouchers are payments/,
      /not converted/,
    ]) {
      expect(within(list).getByText(text)).toBeVisible();
    }
    expect(within(list).queryByRole("button")).not.toBeInTheDocument();
    expect(within(list).getAllByRole("alert")).toHaveLength(4); // warnings and limitations
  });

  it("renders nothing when there is nothing to say", () => {
    const { container } = render(<Warnings unverifiedGates={[]} notes={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("dates", () => {
  it("shows the company's day in a Los Angeles browser (TZ-1.1)", () => {
    render(<TimeText value="2026-03-31T18:30:00Z" timeZone="Asia/Kolkata" />);
    expect(screen.getByText("01 Apr 2026, 00:00")).toBeInTheDocument();
  });

  it("shows a DATE as it is in the books", () => {
    render(<DateText value="2026-04-01" />);
    expect(screen.getByText("01 Apr 2026")).toBeInTheDocument();
  });
});

describe("ScrollableTable", () => {
  it("scrolls inside its own box (NFR-UI-1)", () => {
    render(
      <ScrollableTable caption="Bills">
        <tbody>
          <tr>
            <td>S-1</td>
          </tr>
        </tbody>
      </ScrollableTable>,
    );
    expect(screen.getByRole("table", { name: "Bills" }).parentElement).toHaveClass(
      "overflow-x-auto",
    );
  });
});

describe("ConfirmDialog", () => {
  it("needs the typed word before it confirms", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Revoke Agent"
        confirmLabel="Revoke"
        typed="REVOKE"
        onConfirm={onConfirm}
        onCancel={() => {}}
      >
        The Agent stops syncing.
      </ConfirmDialog>,
    );
    const button = screen.getByRole("button", { name: "Revoke" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "REVOKE");
    await userEvent.click(button);
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
