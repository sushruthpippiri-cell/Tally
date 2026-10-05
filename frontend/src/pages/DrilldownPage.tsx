import { Link, useParams, useSearchParams } from "react-router-dom";
import type { Schemas } from "../api/types";
import { ExportLinks } from "../components/ExportLinks";
import { FilterBar } from "../components/FilterBar";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { Warnings } from "../components/Warnings";
import { DateText, EmptyState } from "../components/ui";
import { humanize } from "../lib/format";
import { useCompany } from "../lib/company";
import { useFilters, withFilters } from "../lib/filters";
import { toInt } from "../lib/integers";
import { Loaded, useCompanyQuery } from "../lib/queries";

const PAGE_SIZE = 50;

/** The rows behind a figure (FR-DD-1-5), a page at a time. The total is the backend's, over
 * every row of every page (FR-DD-5); it is never the sum of the rows on screen (D-051 #5).
 * Mapped custom fields are shown beside each row (DR-UDF-2). */
export function DrilldownPage() {
  const { metric = "" } = useParams();
  const company = useCompany();
  const { filters } = useFilters();
  const [params, setParams] = useSearchParams();
  const by = params.getAll("by");
  const page = Math.max(toInt(params.get("page") ?? "1") ?? 1, 1);
  const query = useCompanyQuery<Schemas["DrilldownOut"]>(`/analytics/${metric}/drilldown`, {
    query: { ...filters, by, page, page_size: PAGE_SIZE },
  });
  const goTo = (n: number) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("page", String(n));
      return next;
    });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{humanize(metric)}: vouchers</h1>
        <ExportLinks report={metric} extra={{ by }} />
      </div>
      <FilterBar />
      <Loaded query={query} label="Loading the vouchers">
        {(d) => {
          const dims = [...new Set(d.rows.flatMap((r) => Object.keys(r.dimensions)))].filter(
            (k) => !k.endsWith("_id"),
          );
          const fields = [...new Set(d.rows.flatMap((r) => Object.keys(r.custom_fields ?? {})))];
          const pages = Math.max(Math.ceil(d.total_rows / d.page_size), 1);
          return (
            <>
              <p className="flex flex-wrap items-baseline gap-2">
                <span className="text-slate-600">Total</span>
                <span className="text-2xl font-semibold">
                  {d.total === null || d.total === undefined ? (
                    "Opening balance unavailable"
                  ) : (
                    <Money value={d.total} />
                  )}
                </span>
                <span className="text-sm text-slate-600">
                  {d.total_rows} {d.total_rows === 1 ? "row" : "rows"}
                </span>
              </p>
              <Warnings
                warnings={d.filters_applied.not_applicable?.map(
                  (f) => `The ${f.replace("_", " ")} filter does not apply to this figure.`,
                )}
              />
              {d.rows.length === 0 ? (
                <EmptyState>No vouchers.</EmptyState>
              ) : (
                <ScrollableTable caption={`${humanize(metric)} vouchers`}>
                  <thead className="bg-slate-100">
                    <tr>
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">Voucher</th>
                      <th className="px-3 py-2">Type</th>
                      <th className="px-3 py-2">Ledger</th>
                      {dims.map((k) => (
                        <th key={k} className="px-3 py-2">
                          {humanize(k)}
                        </th>
                      ))}
                      {fields.map((k) => (
                        <th key={`cf-${k}`} className="px-3 py-2">
                          {humanize(k)}
                        </th>
                      ))}
                      <th className="px-3 py-2 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.rows.map((r, i) => (
                      <tr
                        key={`${r.voucher_id ?? "opening"}-${i}`}
                        className="border-t border-slate-200"
                      >
                        <td className="px-3 py-2">
                          <DateText value={r.voucher_date} />
                        </td>
                        <td className="px-3 py-2">
                          {r.voucher_id ? (
                            <Link
                              to={`/c/${company.company_id}/vouchers/${r.voucher_id}${withFilters(filters)}`}
                              className="underline"
                            >
                              {r.voucher_number ?? "(no number)"}
                            </Link>
                          ) : (
                            r.voucher_type_name
                          )}
                        </td>
                        <td className="px-3 py-2">{r.voucher_type_name}</td>
                        <td className="px-3 py-2">{r.ledger_name ?? ""}</td>
                        {dims.map((k) => (
                          <td key={k} className="px-3 py-2">
                            {r.dimensions[k] ?? ""}
                          </td>
                        ))}
                        {fields.map((k) => (
                          <td key={`cf-${k}`} className="px-3 py-2">
                            {String(r.custom_fields?.[k] ?? "")}
                          </td>
                        ))}
                        <td className="px-3 py-2 text-right">
                          {r.amount === null || r.amount === undefined ? (
                            "Unavailable"
                          ) : (
                            <Money value={r.amount} />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </ScrollableTable>
              )}
              {pages > 1 && (
                <nav aria-label="Pages" className="flex items-center gap-3 text-sm">
                  <button
                    type="button"
                    className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
                    disabled={page <= 1}
                    onClick={() => goTo(page - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page} of {pages}
                  </span>
                  <button
                    type="button"
                    className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50"
                    disabled={page >= pages}
                    onClick={() => goTo(page + 1)}
                  >
                    Next
                  </button>
                </nav>
              )}
            </>
          );
        }}
      </Loaded>
    </section>
  );
}
