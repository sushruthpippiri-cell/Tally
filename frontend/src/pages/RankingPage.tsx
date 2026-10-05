import { useState } from "react";
import { Link } from "react-router-dom";
import type { Schemas } from "../api/types";
import { FilterBar } from "../components/FilterBar";
import { Money } from "../components/Money";
import { ExportLinks } from "../components/ExportLinks";
import { ScrollableTable } from "../components/ScrollableTable";
import { Warnings } from "../components/Warnings";
import { EmptyState } from "../components/ui";
import { formatQuantity } from "../lib/format";
import { useCompany } from "../lib/company";
import { useFilters, withFilters } from "../lib/filters";
import { Loaded, useCompanyQuery } from "../lib/queries";

type Kind = "customers" | "suppliers" | "products";
// kind -> (the metric its rows drill into, its group_by option, a row's noun)
const DRILL: Record<Kind, [string, string, string]> = {
  customers: ["customer-revenue", "customer", "Customer"],
  suppliers: ["supplier-purchases", "supplier", "Supplier"],
  products: ["product-revenue", "product", "Product"],
};

/** A ranking (TOPN-1.x): labelled "Top N" with "View All" (TOPN-1.3), never totalled
 * (TOPN-1.4); Unattributed shown apart, never ranked; the reference total and, for products,
 * Product-attributed Revenue and exactly one difference label (ACC-VAL-1), all the backend's. */
export function RankingTable({ kind }: { kind: Kind }) {
  const company = useCompany();
  const { filters } = useFilters();
  const [viewAll, setViewAll] = useState(false);
  const [rankBy, setRankBy] = useState<"revenue" | "quantity">("revenue");
  const query = useCompanyQuery<Schemas["RankingOut"]>(`/analytics/${kind}`, {
    query: { from: filters.from, to: filters.to, view_all: viewAll, rank_by: rankBy },
  });
  const [metric, option, noun] = DRILL[kind];
  const drill = (key: string) =>
    `/c/${company.company_id}/analytics/${metric}/drilldown${withFilters(filters, {
      by: [`${option}:${key}`],
    })}`;
  return (
    <section className="space-y-3">
      <Loaded query={query} label={`Loading ${kind}`}>
        {(r) => (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">
                {r.label} {kind}
                <span className="ml-2 text-sm font-normal text-slate-600">of {r.total_count}</span>
              </h2>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {kind === "products" && (
                  <select
                    aria-label="Rank by"
                    className="rounded border border-slate-300 bg-white px-2 py-1"
                    value={rankBy}
                    onChange={(e) => setRankBy(e.target.value as "revenue" | "quantity")}
                  >
                    <option value="revenue">By revenue</option>
                    <option value="quantity">By quantity</option>
                  </select>
                )}
                <ExportLinks
                  report={kind}
                  extra={{ rank_by: rankBy, view_all: viewAll ? "true" : undefined }}
                />
                <button
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1"
                  onClick={() => setViewAll(!viewAll)}
                >
                  {r.is_top_n ? "View All" : `Top ${r.n ?? ""}`.trim()}
                </button>
              </div>
            </div>
            <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
              {[r.reference_total, r.product_attributed, r.difference, r.unattributed]
                .filter((x): x is Schemas["LabelledAmount"] => Boolean(x))
                .map((x) => (
                  <div key={x.label} className="contents">
                    <dt className="text-slate-600">{x.label}</dt>
                    <dd>
                      {x.amount === null || x.amount === undefined ? (
                        "Unavailable"
                      ) : x === r.unattributed ? (
                        <Link to={drill("none")} className="underline">
                          <Money value={x.amount} />
                        </Link>
                      ) : (
                        <Money value={x.amount} />
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
            <Warnings notes={r.notes} />
            {r.rows.length === 0 ? (
              <EmptyState>Nothing in this period.</EmptyState>
            ) : (
              <ScrollableTable caption={`${r.label} ${kind}`}>
                <thead className="bg-slate-100">
                  <tr>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">{noun}</th>
                    <th className="px-3 py-2 text-right">
                      {rankBy === "quantity" ? "Quantity" : "Amount"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {r.rows.map((row) => (
                    <tr key={`${row.id}-${row.unit ?? ""}`} className="border-t border-slate-200">
                      <td className="px-3 py-2">{row.rank}</td>
                      <td className="px-3 py-2">
                        <Link to={drill(row.id)} className="underline">
                          {row.name}
                        </Link>
                        {row.multiple_units && (
                          <span className="ml-1 text-xs text-amber-800">
                            (sold in several units)
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {row.amount ? (
                          <Money value={row.amount} />
                        ) : (
                          `${row.quantity ? formatQuantity(row.quantity) : ""} ${row.unit ?? ""}`
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

function RankingPage({ title, kind }: { title: string; kind: Kind }) {
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{title}</h1>
      <FilterBar pickers={false} />
      <RankingTable kind={kind} />
    </section>
  );
}

export const CustomersPage = () => <RankingPage title="Customers" kind="customers" />;
export const ProductsPage = () => <RankingPage title="Products" kind="products" />;
