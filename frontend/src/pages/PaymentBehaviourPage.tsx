import type { Schemas } from "../api/types";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { ExportLinks } from "../components/ExportLinks";
import { Warnings } from "../components/Warnings";
import { DateText, EmptyState } from "../components/ui";
import { Loaded, useCompanyQuery } from "../lib/queries";

const cell = "px-3 py-2";

export function usePaymentBehaviour() {
  return useCompanyQuery<Schemas["PaymentBehaviourOut"]>("/analytics/payment-behaviour");
}

/** FR-PAY-1-6: average days to pay, per customer; "insufficient history" below the minimum.
 * Hidden until gate G25 passes (FR-PAY-6): its navigation entry appears only then. */
export function PaymentBehaviourPage() {
  const query = usePaymentBehaviour();
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Payment Behaviour</h1>
        <ExportLinks report="payment-behaviour" />
      </div>
      <Loaded query={query} label="Loading payment behaviour">
        {(p) =>
          !p.available ? (
            <EmptyState>{p.reason ?? "Not available yet."}</EmptyState>
          ) : (
            <>
              <p className="text-sm text-slate-600">
                Receipts after <DateText value={p.window_from} /> up to{" "}
                <DateText value={p.window_to} />
              </p>
              <Warnings notes={p.notes} unverifiedGates={p.unverified_gates} />
              <ScrollableTable caption="Payment behaviour by customer">
                <thead className="bg-slate-100">
                  <tr>
                    <th className={cell}>Customer</th>
                    <th className={`${cell} text-right`}>Settlements</th>
                    <th className={`${cell} text-right`}>Settled</th>
                    <th className={`${cell} text-right`}>Average days to pay</th>
                    <th className={`${cell} text-right`}>Average days past due</th>
                  </tr>
                </thead>
                <tbody>
                  {[...(p.overall ? [p.overall] : []), ...p.customers].map((c) => (
                    <tr key={c.ledger_id ?? "all"} className="border-t border-slate-200">
                      <td className={cell}>{c.ledger_name ?? "All customers"}</td>
                      <td className={`${cell} text-right`}>{c.settlements}</td>
                      <td className={`${cell} text-right`}>
                        <Money value={c.settled_amount} />
                      </td>
                      <td className={`${cell} text-right`} colSpan={c.insufficient_history ? 2 : 1}>
                        {c.insufficient_history ? "insufficient history" : c.avg_days_to_pay}
                      </td>
                      {!c.insufficient_history && (
                        <td className={`${cell} text-right`}>{c.avg_days_past_due ?? ""}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </ScrollableTable>
            </>
          )
        }
      </Loaded>
    </section>
  );
}
