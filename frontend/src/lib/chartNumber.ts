import { formatMoney } from "./format";

/** The one place a money string becomes a JavaScript number (D-053 #5), and only to size a
 * chart's shapes: a bar's length, a point's height. A float may not hold every digit of the
 * amount, which does not matter for a shape; nothing drawn from this number is ever shown as
 * text. Every label, tooltip and axis value shows the backend's string through `formatMoney`.
 *
 * The second file exempt from the no-conversion lint rule (with `integers.ts`); a test fails if
 * any other file converts money. Throws on anything `formatMoney` would refuse. */
export function toChartNumber(amount: string): number {
  formatMoney(amount); // a malformed amount is a bug to see, never a shape to guess
  return Number(amount);
}
