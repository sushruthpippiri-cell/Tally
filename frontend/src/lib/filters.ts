import { useSearchParams } from "react-router-dom";
import { toInt } from "./integers";

/** FR-4.3: the global filters live in the URL query string, so drill-downs, back navigation and
 * shared links keep them. Dates are "YYYY-MM-DD"; the others are ids. Left out, the backend
 * uses the financial year to date. */
export const FILTER_KEYS = ["from", "to", "customer", "product", "cost_centre"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string>>;

export function readFilters(params: URLSearchParams): Filters {
  const filters: Filters = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return filters;
}

/** "?from=…&customer=…" for a link that keeps the filters (plus any extra parameters). */
export function withFilters(
  filters: Filters,
  extra: Record<string, string | readonly string[] | undefined> = {},
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (Array.isArray(value)) for (const item of value) params.append(key, item);
    else if (typeof value === "string" && value) params.set(key, value);
  }
  const search = params.toString();
  return search ? `?${search}` : "";
}

export function useFilters(): { filters: Filters; set: (patch: Filters) => void } {
  const [params, setParams] = useSearchParams();
  const set = (patch: Filters) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      next.delete("page"); // a new filter starts from the first page
      return next;
    });
  return { filters: readFilters(params), set };
}

// --- periods (FR-4.1's period selector), on DATE strings only: never through Date (D-051 #6) --

type Ymd = [number, number, number];

function parse(value: string): Ymd {
  const [y, m, d] = value.split("-").map((part) => toInt(part) ?? 0);
  return [y ?? 0, m ?? 1, d ?? 1];
}

function iso([y, m, d]: Ymd): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function daysIn(y: number, m: number): number {
  if (m === 2) return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28;
  return [4, 6, 9, 11].includes(m) ? 30 : 31;
}

function dayBefore([y, m, d]: Ymd): Ymd {
  if (d > 1) return [y, m, d - 1];
  return m > 1 ? [y, m - 1, daysIn(y, m - 1)] : [y - 1, 12, 31];
}

function addMonths([y, m, d]: Ymd, months: number): Ymd {
  const index = y * 12 + (m - 1) + months;
  return [Math.floor(index / 12), (index % 12) + 1, d];
}

function before(a: Ymd, b: Ymd): boolean {
  return iso(a) < iso(b);
}

/** Today's date in the company's time zone (TZ-1.1), not the browser's. */
export function todayIn(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
}

export interface Period {
  label: string;
  from: string;
  to: string;
}

/** The presets: this and last financial year, this financial quarter, this and last month.
 * `fyStart` is the company's financial year start (only its month and day count). */
export function periodPresets(today: string, fyStart: string): Period[] {
  const now = parse(today);
  const [, fm, fd] = parse(fyStart);
  let start: Ymd = [now[0], fm, fd];
  if (before(now, start)) start = [now[0] - 1, fm, fd];
  let quarter = start;
  for (const months of [3, 6, 9]) {
    const next = addMonths(start, months);
    if (!before(now, next)) quarter = next;
  }
  const lastStart: Ymd = [start[0] - 1, fm, fd];
  const month: Ymd = [now[0], now[1], 1];
  const lastMonth = addMonths(month, -1);
  return [
    { label: "This financial year", from: iso(start), to: today },
    { label: "Last financial year", from: iso(lastStart), to: iso(dayBefore(start)) },
    { label: "This quarter", from: iso(quarter), to: today },
    { label: "This month", from: iso(month), to: today },
    { label: "Last month", from: iso(lastMonth), to: iso(dayBefore(month)) },
  ];
}

/** The last day of a DATE's month ("2025-02-10" -> "2025-02-28"). */
export function monthEnd(value: string): string {
  const [y, m] = parse(value);
  return iso([y, m, daysIn(y, m)]);
}
