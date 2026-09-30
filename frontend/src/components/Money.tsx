import type { Schemas } from "../api/types";
import { formatMoney } from "../lib/format";

/** An amount from the API, shown as it came (a decimal string); never added up here. */
export function Money({ value }: { value: string }) {
  return <span className="whitespace-nowrap tabular-nums">{formatMoney(value)}</span>;
}

/** A backend Figure: an amount (Dr/Cr for balances), or "unavailable" with the ledgers named.
 * An unavailable balance is never shown as ₹0 (ACC-9.6, D-051 #7). */
export function Figure({ figure }: { figure: Schemas["Figure"] }) {
  if (!figure.available || figure.amount === null || figure.amount === undefined) {
    const names = figure.unavailable_ledgers ?? [];
    const count = figure.unavailable_count ?? names.length;
    const more = count > names.length ? ` and ${count - names.length} more` : "";
    return (
      <span className="text-amber-800">
        Opening balance unavailable
        {names.length > 0 && (
          <span className="block text-sm">
            Missing for: {names.join(", ")}
            {more}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="whitespace-nowrap tabular-nums">
      {formatMoney(figure.amount)}
      {figure.direction && <span className="ml-1 text-sm text-slate-600">{figure.direction}</span>}
    </span>
  );
}
