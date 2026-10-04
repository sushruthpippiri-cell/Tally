import { Link, useSearchParams } from "react-router-dom";
import type { Schemas } from "../api/types";
import { Figure, Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { ExportLinks } from "../components/ExportLinks";
import { Warnings } from "../components/Warnings";
import { Badge, DateText, EmptyState } from "../components/ui";
import { useCompany } from "../lib/company";
import { Loaded, useCompanyQuery } from "../lib/queries";

type Side = "receivable" | "payable";
const cell = "px-3 py-2";
const EXTRAS: [keyof Schemas["AgingRow"], string][] = [
  ["credit", "Credit (over-settled)"],
  ["unadjusted_advances", "Unadjusted advances"],
  ["on_account", "On account"],
  ["unmatched_settlements", "Unmatched settlements"],
  ["net_exposure", "Net exposure"],
];

/** SRS 10: party -> bills -> allocations -> voucher, as of the `to` date (default today in the
 * company's time zone). Every amount is the backend's. */
export function AgingPage() {
  const [params, setParams] = useSearchParams();
  const side = (params.get("side") === "payable" ? "payable" : "receivable") as Side;
  const ledger = params.get("ledger");
  const reference = params.get("reference");
  const asOf = params.get("to") ?? undefined;
  const open = (patch: Record<string, string | null>) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      return next;
    });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Aging</h1>
        <ExportLinks report={`aging-${side}`} />
      </div>
      <label className="flex flex-col text-xs">
        Side
        <select
          className="w-48 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={side}
          onChange={(e) => open({ side: e.target.value, ledger: null, reference: null })}
        >
          <option value="receivable">Receivables</option>
          <option value="payable">Payables</option>
        </select>
      </label>
      {reference && ledger ? (
        <Allocations side={side} ledger={ledger} reference={reference} asOf={asOf} />
      ) : ledger ? (
        <Bills side={side} ledger={ledger} asOf={asOf} onOpen={(r) => open({ reference: r })} />
      ) : (
        <Parties side={side} asOf={asOf} onOpen={(id) => open({ ledger: id })} />
      )}
    </section>
  );
}

function Parties({
  side,
  asOf,
  onOpen,
}: {
  side: Side;
  asOf: string | undefined;
  onOpen: (ledger: string) => void;
}) {
  const query = useCompanyQuery<Schemas["AgingOut"]>("/analytics/aging", {
    query: { side, as_of: asOf },
  });
  return (
    <Loaded query={query} label="Loading aging">
      {(a) => (
        <>
          <p className="text-sm text-slate-600">
            As of <DateText value={a.as_of} />
          </p>
          <Warnings unverifiedGates={a.unverified_gates} />
          {a.parties.length === 0 ? (
            <EmptyState>No bills outstanding.</EmptyState>
          ) : (
            <ScrollableTable caption={`Aged ${side}s`}>
              <thead className="bg-slate-100">
                <tr>
                  <th className={cell}>Party</th>
                  {a.bucket_order.map((b) => (
                    <th key={b.key} className={`${cell} text-right`}>
                      {b.label}
                    </th>
                  ))}
                  {EXTRAS.map(([, label]) => (
                    <th key={label} className={`${cell} text-right`}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...a.parties, { ...a.total, ledger_name: "Total" }].map((p) => (
                  <tr key={p.ledger_id ?? "total"} className="border-t border-slate-200">
                    <td className={cell}>
                      {p.ledger_id ? (
                        <button
                          type="button"
                          className="underline"
                          onClick={() => onOpen(p.ledger_id ?? "")}
                        >
                          {p.ledger_name}
                        </button>
                      ) : (
                        <strong>{p.ledger_name}</strong>
                      )}
                    </td>
                    {a.bucket_order.map((b) => (
                      <td key={b.key} className={`${cell} text-right`}>
                        <Money value={p.buckets[b.key] ?? "0"} />
                      </td>
                    ))}
                    {EXTRAS.map(([key]) => (
                      <td key={key} className={`${cell} text-right`}>
                        <Money value={String(p[key])} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
          )}
          {a.no_bill_details.length > 0 && (
            <ScrollableTable caption="Parties without bill details">
              <thead className="bg-slate-100">
                <tr>
                  <th className={cell}>Party</th>
                  <th className={`${cell} text-right`}>Balance</th>
                  <th className={cell}>Note</th>
                </tr>
              </thead>
              <tbody>
                {a.no_bill_details.map((n) => (
                  <tr key={n.ledger_id} className="border-t border-slate-200">
                    <td className={cell}>{n.ledger_name}</td>
                    <td className={`${cell} text-right`}>
                      <Figure figure={n.balance} />
                    </td>
                    <td className={cell}>{n.note}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
          )}
        </>
      )}
    </Loaded>
  );
}

function Bills({
  side,
  ledger,
  asOf,
  onOpen,
}: {
  side: Side;
  ledger: string;
  asOf: string | undefined;
  onOpen: (reference: string) => void;
}) {
  const query = useCompanyQuery<Schemas["BillsOut"]>("/analytics/aging/bills", {
    query: { side, ledger_id: ledger, as_of: asOf },
  });
  return (
    <Loaded query={query} label="Loading bills">
      {(b) => (
        <>
          <Warnings unverifiedGates={b.unverified_gates} />
          <ScrollableTable caption="Bills">
            <thead className="bg-slate-100">
              <tr>
                <th className={cell}>Bill</th>
                <th className={cell}>Bill date</th>
                <th className={cell}>Due</th>
                <th className={`${cell} text-right`}>Days overdue</th>
                <th className={`${cell} text-right`}>Outstanding</th>
              </tr>
            </thead>
            <tbody>
              {b.bills.map((bill) => (
                <tr key={bill.reference_name} className="border-t border-slate-200">
                  <td className={cell}>
                    <button
                      type="button"
                      className="underline"
                      onClick={() => onOpen(bill.reference_name)}
                    >
                      {bill.reference_name}
                    </button>
                    {bill.unverified && (
                      <span className="ml-1">
                        <Badge tone="warn">unverified</Badge>
                      </span>
                    )}
                  </td>
                  <td className={cell}>
                    <DateText value={bill.bill_date} />
                  </td>
                  <td className={cell}>
                    <DateText value={bill.due_date} />
                  </td>
                  <td className={`${cell} text-right`}>{bill.days_overdue ?? ""}</td>
                  <td className={`${cell} text-right`}>
                    <Money value={bill.outstanding} />
                    {bill.is_credit && " Cr"}
                  </td>
                </tr>
              ))}
            </tbody>
          </ScrollableTable>
        </>
      )}
    </Loaded>
  );
}

function Allocations({
  side,
  ledger,
  reference,
  asOf,
}: {
  side: Side;
  ledger: string;
  reference: string;
  asOf: string | undefined;
}) {
  const company = useCompany();
  const query = useCompanyQuery<Schemas["AllocationsOut"]>("/analytics/aging/allocations", {
    query: { side, ledger_id: ledger, reference, as_of: asOf },
  });
  return (
    <Loaded query={query} label="Loading the bill's allocations">
      {(a) => (
        <ScrollableTable caption={`Bill ${a.reference_name}`}>
          <thead className="bg-slate-100">
            <tr>
              <th className={cell}>Date</th>
              <th className={cell}>Voucher</th>
              <th className={cell}>Allocation</th>
              <th className={`${cell} text-right`}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {a.allocations.map((x, i) => (
              <tr key={i} className="border-t border-slate-200">
                <td className={cell}>
                  <DateText value={x.voucher_date} />
                </td>
                <td className={cell}>
                  {x.voucher_id ? (
                    <Link
                      to={`/c/${company.company_id}/vouchers/${x.voucher_id}`}
                      className="underline"
                    >
                      {x.voucher_type_name} {x.voucher_number ?? ""}
                    </Link>
                  ) : (
                    "Opening bill"
                  )}
                </td>
                <td className={cell}>{x.allocation_type}</td>
                <td className={`${cell} text-right`}>
                  <Money value={x.amount} />
                </td>
              </tr>
            ))}
          </tbody>
        </ScrollableTable>
      )}
    </Loaded>
  );
}
