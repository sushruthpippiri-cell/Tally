/** Formatting for the screen (D-051 #5, #6).
 *
 * Money arrives as a decimal string and is formatted from its digits: rounded to 2 places half
 * away from zero, grouped the Indian way (₹1,23,45,678.90). It is never turned into a JavaScript
 * number, and `Intl.NumberFormat` is not used for it: older engines, still common on Indian
 * Android phones, convert the string to a float first.
 *
 * Dates are shown in the company's time zone, never the browser's (TZ-1.1): a DATE is
 * formatted from its parts; a timestamp through Intl with `timeZone`. */

const DECIMAL = /^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

/** "1" + "999" -> "1000": adds one to a string of digits. */
function increment(digits: string): string {
  const out = digits.split("");
  for (let i = out.length - 1; i >= 0; i -= 1) {
    if (out[i] !== "9") {
      out[i] = String.fromCharCode((out[i] ?? "0").charCodeAt(0) + 1);
      return out.join("");
    }
    out[i] = "0";
  }
  return `1${out.join("")}`;
}

/** Moves the decimal point by `exponent` places ("1.25", 2 -> "125"). */
function shift(whole: string, fraction: string, exponent: number): [string, string] {
  const digits = whole + fraction;
  const point = whole.length + exponent;
  if (point <= 0) return ["0", "0".repeat(-point) + digits];
  if (point >= digits.length) return [digits + "0".repeat(point - digits.length), ""];
  return [digits.slice(0, point), digits.slice(point)];
}

/** "1234567" -> "12,34,567": the last three digits, then groups of two. */
function groupIndian(whole: string): string {
  if (whole.length <= 3) return whole;
  const head = whole.slice(0, -3);
  const pairs = head.length % 2 === 1 ? [head.slice(0, 1)] : [];
  for (let i = head.length % 2; i < head.length; i += 2) pairs.push(head.slice(i, i + 2));
  return `${pairs.join(",")},${whole.slice(-3)}`;
}

/** "12345678.9000" -> "₹1,23,45,678.90"; "-1.005" -> "-₹1.01". Throws on anything that is not
 * a decimal number: a malformed amount is a bug to see, never a figure to guess. */
export function formatMoney(value: string): string {
  const match = DECIMAL.exec(value.trim());
  const [, sign, rawWhole = "", rawFraction = "", exponent] = match ?? [];
  if (!match || (rawWhole === "" && rawFraction === "")) {
    throw new Error(`not a decimal amount: ${JSON.stringify(value)}`);
  }
  const [whole, fraction] = shift(
    rawWhole || "0",
    rawFraction,
    exponent === undefined ? 0 : exponentValue(exponent),
  );
  const padded = fraction.padEnd(3, "0");
  let cents = (whole.replace(/^0+(?=\d)/, "") || "0") + padded.slice(0, 2);
  if ((padded[2] ?? "0") >= "5") cents = increment(cents); // half away from zero
  const paise = cents.slice(-2);
  const rupees = cents.slice(0, -2).replace(/^0+(?=\d)/, "") || "0";
  const zero = /^0+$/.test(cents);
  return `${sign === "-" && !zero ? "-" : ""}₹${groupIndian(rupees)}.${paise}`;
}

function exponentValue(text: string): number {
  // An exponent is an index, not money: read it digit by digit.
  const negative = text.startsWith("-");
  let n = 0;
  for (const ch of text.replace(/^[+-]/, "")) n = n * 10 + (ch.charCodeAt(0) - 48);
  return negative ? -n : n;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A DATE ("2026-03-16") -> "16 Mar 2026", from its parts: never through `new Date()`, which
 * would move it to the previous day in a browser west of UTC. */
export function formatDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error(`not a date: ${JSON.stringify(value)}`);
  const [, year, month, day] = match;
  return `${day} ${MONTHS[monthIndex(month ?? "")]} ${year}`;
}

function monthIndex(month: string): number {
  return (month.charCodeAt(0) - 48) * 10 + (month.charCodeAt(1) - 48) - 1;
}

/** A timestamp -> "01 Apr 2026, 00:00" in the company's time zone (TZ-1.1). */
export function formatTimestamp(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}
