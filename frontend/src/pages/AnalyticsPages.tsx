import { useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { Schemas } from "../api/types";
import { Chart } from "../components/Chart";
import { ExportLinks } from "../components/ExportLinks";
import { FilterBar } from "../components/FilterBar";
import { Figure } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { Warnings } from "../components/Warnings";
import { EmptyState } from "../components/ui";
import { useCompany } from "../lib/company";
import { monthEnd, useFilters, withFilters, type Filters } from "../lib/filters";
import { Loaded, useCompanyQuery } from "../lib/queries";
import { RankingTable } from "./RankingPage";

type MetricOut = Schemas["MetricOut"];

const FILTER_NAMES: Record<string, string> = {
  customer: "customer",
  product: "product",
  cost_centre: "cost centre",
};

/** The drill-down page of a metric, narrowed by `by` keys, with the filters kept. */
export function drillLink(
  companyId: string,
  metric: string,
  filters: Filters,
  by: string[],
): string {
  return `/c/${companyId}/analytics/${metric}/drilldown${withFilters(filters, { by })}`;
}

/** A metric's figure (the backend's total), its monthly chart, and its breakdown, each row
 * drilling one level down (`levels`, the group_by chain) and then to the vouchers (FR-DD-1-5).
 * Every amount is the backend's; nothing is added up here (D-051 #5). */
export function MetricSection({
  metric,
  title,
  levels,
  chart = false,
  children,
}: {
  metric: string;
  title: string;
  levels: string[];
  chart?: boolean;
  children?: (data: MetricOut) => ReactNode;
}) {
  const company = useCompany();
  const navigate = useNavigate();
  const { filters } = useFilters();
  const [params] = useSearchParams();
  const by = params.getAll("by").filter((b) => levels.includes(b.split(":")[0] ?? ""));
  const depth = Math.min(by.length, levels.length - 1);
  const level = levels[depth] ?? levels[0];
  const query = useCompanyQuery<MetricOut>(`/analytics/${metric}`, {
    query: { ...filters, group_by: level, by },
  });
  return (
    <section aria-labelledby={`${metric}-title`} className="space-y-3">
      <Loaded query={query} label={`Loading ${title}`}>
        {(m) => (
          <>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id={`${metric}-title`} className="text-lg font-semibold">
                {m.label ?? title}
              </h2>
              <p className="text-2xl font-semibold">
                <Figure figure={m.summary} />
              </p>
            </div>
            {by.length > 0 && (
              <p className="text-sm">
                Showing one {by.map((b) => b.split(":")[0]?.replace("_", " ")).join(" › ")}.{" "}
                <Link to={withFilters(filters)} className="underline">
                  Show all
                </Link>
              </p>
            )}
            <Warnings
              warnings={m.filters_applied.not_applicable?.map(
                (f) => `The ${FILTER_NAMES[f] ?? f} filter does not apply to ${title}.`,
              )}
              notes={m.notes}
            />
            {children?.(m)}
            {chart && m.series.length > 0 && (
              <Chart
                title={`${m.label ?? title} by month`}
                points={m.series
                  .filter((p): p is typeof p & { amount: string } => p.amount !== null)
                  .map((p) => ({ key: p.start, label: p.period, amount: p.amount }))}
                onSelect={(start) =>
                  navigate(
                    drillLink(
                      company.company_id,
                      metric,
                      { ...filters, from: start, to: monthEnd(start) },
                      by,
                    ),
                  )
                }
              />
            )}
            {m.breakdown.length === 0 ? (
              <EmptyState>Nothing in this period.</EmptyState>
            ) : (
              <ScrollableTable caption={`${title} by ${level?.replace("_", " ")}`}>
                <thead className="bg-slate-100">
                  <tr>
                    <th className="px-3 py-2 capitalize">{level?.replace("_", " ")}</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {m.breakdown.map((b) => {
                    const next = [...by, `${level}:${b.key ?? "none"}`];
                    const to =
                      depth + 1 < levels.length
                        ? withFilters(filters, { by: next })
                        : drillLink(company.company_id, metric, filters, next);
                    return (
                      <tr key={b.key ?? "none"} className="border-t border-slate-200">
                        <td className="px-3 py-2">
                          <Link to={to} className="underline">
                            {b.label ?? "Unattributed"}
                          </Link>
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Figure figure={b.figure} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </ScrollableTable>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Link
                to={drillLink(company.company_id, metric, filters, by)}
                className="text-sm underline"
              >
                See every voucher behind {m.label ?? title}
              </Link>
              <ExportLinks report={metric} extra={{ group_by: level, by }} />
            </div>
          </>
        )}
      </Loaded>
    </section>
  );
}

function Page({
  title,
  children,
  pickers = true,
}: {
  title: string;
  children: ReactNode;
  pickers?: boolean;
}) {
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{title}</h1>
      <FilterBar pickers={pickers} />
      {children}
    </section>
  );
}

/** Sales: Total Sales Revenue, and beside it Product-attributed Revenue and exactly one
 * difference label, the backend's (ACC-VAL-1, EXP-1.4). */
export function SalesPage() {
  const company = useCompany();
  const { filters } = useFilters();
  const base = `/c/${company.company_id}`;
  return (
    <Page title="Sales">
      <MetricSection metric="sales" title="Total Sales Revenue" levels={["ledger"]} chart>
        {(m) =>
          m.filters_applied.not_applicable?.includes("customer") && filters.customer ? (
            <Link
              to={drillLink(company.company_id, "customer-revenue", filters, [
                `customer:${filters.customer}`,
              ])}
              className="text-sm underline"
            >
              See this customer's revenue
            </Link>
          ) : null
        }
      </MetricSection>
      <MetricSection
        metric="product-revenue"
        title="Product-attributed Revenue"
        levels={["product"]}
      />
      <MetricSection metric="product-difference" title="Difference" levels={["voucher"]} />
      <p className="flex gap-4 text-sm">
        <Link to={`${base}/customers${withFilters(filters)}`} className="underline">
          By customer
        </Link>
        <Link to={`${base}/products${withFilters(filters)}`} className="underline">
          By product
        </Link>
      </p>
    </Page>
  );
}

export function PurchasesPage() {
  return (
    <Page title="Purchases">
      <MetricSection metric="purchases" title="Purchase Value" levels={["ledger"]} chart />
      <RankingTable kind="suppliers" />
    </Page>
  );
}

export function CashFlowPage() {
  return (
    <Page title="Cash Flow">
      <MetricSection metric="cash-flow" title="Net cash flow" levels={["flow"]} chart />
    </Page>
  );
}

export function BalancesPage() {
  return (
    <Page title="Balances" pickers={false}>
      <MetricSection metric="cash-bank-position" title="Cash and bank" levels={["ledger"]} />
      <MetricSection metric="receivables" title="Receivables" levels={["ledger"]} />
      <MetricSection metric="payables" title="Payables" levels={["ledger"]} />
      <MetricSection metric="ledger-balances" title="Ledger balances" levels={["ledger"]} />
    </Page>
  );
}

const EXPENSE_VIEWS: Record<string, string[]> = {
  "Expense category": ["group", "ledger"],
  "Cost centre": ["cost_centre", "ledger"],
};

/** FR-DD-3: expense category -> ledger -> vouchers, or by cost centre. */
export function ExpensesPage() {
  const [view, setView] = useState("Expense category");
  return (
    <Page title="Expenses">
      <label className="flex flex-col text-xs">
        Group by
        <select
          className="w-48 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={view}
          onChange={(e) => setView(e.target.value)}
        >
          {Object.keys(EXPENSE_VIEWS).map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </label>
      <MetricSection
        metric="expenses"
        title="Expenses"
        levels={EXPENSE_VIEWS[view] ?? ["group"]}
        chart
      />
    </Page>
  );
}

/** ACC-5.3: unlinked credit and debit notes, never subtracted from sales or purchases. */
export function UnclassifiedPage() {
  return (
    <Page title="Unclassified Adjustments">
      <MetricSection
        metric="unclassified-adjustments"
        title="Unclassified Adjustments"
        levels={["type", "ledger"]}
      />
    </Page>
  );
}
