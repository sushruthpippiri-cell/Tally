import { useState } from "react";
import type { Schemas } from "../api/types";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { ExportLinks } from "../components/ExportLinks";
import { Warnings } from "../components/Warnings";
import { DateText, EmptyState } from "../components/ui";
import { formatQuantity } from "../lib/format";
import { Loaded, useCompanyQuery } from "../lib/queries";

const cell = "px-3 py-2";
const PERIODS = [30, 60, 90, 180];

/** SRS 11: every item in exactly one class, with the snapshot date it used (FR-STK-16), the
 * stale-snapshot warning and the unit limitation (FR-STK-10), never hidden (D-051 #7). */
export function StockPage() {
  const [period, setPeriod] = useState<number | undefined>(undefined);
  const [movement, setMovement] = useState<string | undefined>(undefined);
  const query = useCompanyQuery<Schemas["StockOut"]>("/analytics/stock", {
    query: { period_days: period, class: movement, page_size: 500 },
  });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Stock</h1>
        <ExportLinks report="stock" extra={{ period_days: period?.toString(), class: movement }} />
      </div>
      <Loaded query={query} label="Loading stock">
        {(s) => (
          <>
            <div className="flex flex-wrap items-end gap-2 text-sm">
              <label className="flex flex-col text-xs">
                Period
                <select
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                  value={s.period_days}
                  onChange={(e) => setPeriod(PERIODS.find((p) => String(p) === e.target.value))}
                >
                  {PERIODS.map((p) => (
                    <option key={p} value={p}>
                      Last {p} days
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-slate-600">
                <DateText value={s.period_from} /> to <DateText value={s.period_to} />; stock as of
                the snapshot dated <DateText value={s.snapshot_dates.newest} />
              </p>
            </div>
            <Warnings
              warnings={s.warnings}
              notes={s.notes}
              limitations={s.limitations}
              unverifiedGates={s.unverified_gates}
            />
            <div className="flex flex-wrap gap-2 text-sm" role="group" aria-label="Movement class">
              <button
                type="button"
                aria-pressed={!movement}
                className={`rounded border px-2 py-1 ${movement ? "border-slate-300" : "border-slate-800 bg-slate-800 text-white"}`}
                onClick={() => setMovement(undefined)}
              >
                All
              </button>
              {s.classes.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  aria-pressed={movement === c.key}
                  className={`rounded border px-2 py-1 ${movement === c.key ? "border-slate-800 bg-slate-800 text-white" : "border-slate-300"}`}
                  onClick={() => setMovement(c.key)}
                >
                  {c.label} ({c.count})
                </button>
              ))}
            </div>
            {s.items.length === 0 ? (
              <EmptyState>No items in this class.</EmptyState>
            ) : (
              <ScrollableTable caption="Stock items">
                <thead className="bg-slate-100">
                  <tr>
                    <th className={cell}>Item</th>
                    <th className={cell}>Class</th>
                    <th className={`${cell} text-right`}>Stock</th>
                    <th className={cell}>Snapshot</th>
                    <th className={cell}>Last sale</th>
                    <th className={`${cell} text-right`}>Sold in period</th>
                    <th className={`${cell} text-right`}>Quantity sold</th>
                  </tr>
                </thead>
                <tbody>
                  {s.items.map((i) => (
                    <tr key={i.stock_item_id} className="border-t border-slate-200">
                      <td className={cell}>{i.name}</td>
                      <td className={cell}>
                        {i.label}
                        {i.note && <span className="block text-xs text-slate-600">{i.note}</span>}
                      </td>
                      <td className={`${cell} text-right tabular-nums`}>
                        {i.stock === null || i.stock === undefined
                          ? "Unknown"
                          : `${formatQuantity(i.stock)} ${i.stock_unit ?? ""}`}
                      </td>
                      <td className={cell}>
                        <DateText value={i.snapshot_date} />
                      </td>
                      <td className={cell}>
                        <DateText value={i.last_sale_date} />
                      </td>
                      <td className={`${cell} text-right`}>
                        <Money value={i.period_sales_value} />
                      </td>
                      <td className={`${cell} text-right tabular-nums`}>
                        {i.period_quantities
                          .map((q) => `${formatQuantity(q.quantity)} ${q.unit ?? ""}`)
                          .join(", ")}
                        {i.multi_unit && (
                          <span className="block text-xs text-amber-800">several units</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </ScrollableTable>
            )}
          </>
        )}
      </Loaded>
    </section>
  );
}
