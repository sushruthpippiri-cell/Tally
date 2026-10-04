import { useParams } from "react-router-dom";
import type { Schemas } from "../api/types";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge, DateText, TimeText } from "../components/ui";
import { formatQuantity, humanize } from "../lib/format";
import { can, useCompany } from "../lib/company";
import { Loaded, useCompanyQuery } from "../lib/queries";

const cell = "px-3 py-2";

/** One voucher as synced (FR-DD-1): its ledger entries with bills and cost centres, its
 * inventory lines and its custom fields (DR-UDF-2); its audit history for Owner and Admin. */
export function VoucherPage() {
  const { voucherId = "" } = useParams();
  const company = useCompany();
  const query = useCompanyQuery<Schemas["VoucherDetailOut"]>(`/vouchers/${voucherId}`);
  return (
    <section className="space-y-4">
      <Loaded query={query} label="Loading the voucher">
        {(v) => (
          <>
            <h1 className="text-xl font-semibold">
              {v.voucher_type_name} {v.voucher_number ?? "(no number)"}
            </h1>
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <DateText value={v.voucher_date} />
              <Badge tone={v.status === "ACTIVE" ? "ok" : "bad"}>{v.status}</Badge>
              <span className="text-slate-600">
                Last synced{" "}
                <TimeText value={v.last_synced_at} timeZone={company.company_timezone} />
              </span>
            </p>
            {v.narration && <p className="text-sm">{v.narration}</p>}
            <ScrollableTable caption="Ledger entries">
              <thead className="bg-slate-100">
                <tr>
                  <th className={cell}>Ledger</th>
                  <th className={cell}>Dr/Cr</th>
                  <th className={`${cell} text-right`}>Amount</th>
                  <th className={cell}>Bills</th>
                  <th className={cell}>Cost centres</th>
                </tr>
              </thead>
              <tbody>
                {v.entries.map((e) => (
                  <tr key={e.line} className="border-t border-slate-200 align-top">
                    <td className={cell}>{e.ledger_name}</td>
                    <td className={cell}>{e.direction}</td>
                    <td className={`${cell} text-right`}>
                      <Money value={e.amount} />
                    </td>
                    <td className={cell}>
                      {e.bills.map((b, i) => (
                        <span key={i} className="block whitespace-nowrap">
                          {b.allocation_type} {b.reference_name ?? ""} <Money value={b.amount} />{" "}
                          {b.direction}
                          {b.due_date && (
                            <>
                              {" "}
                              due <DateText value={b.due_date} />
                            </>
                          )}
                        </span>
                      ))}
                    </td>
                    <td className={cell}>
                      {e.cost_centres.map((c) => (
                        <span key={c.cost_centre_id} className="block whitespace-nowrap">
                          {c.cost_centre_name} <Money value={c.amount} />
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
            {v.items.length > 0 && (
              <ScrollableTable caption="Inventory lines">
                <thead className="bg-slate-100">
                  <tr>
                    <th className={cell}>Item</th>
                    <th className={`${cell} text-right`}>Quantity</th>
                    <th className={`${cell} text-right`}>Rate</th>
                    <th className={`${cell} text-right`}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {v.items.map((i, n) => (
                    <tr key={n} className="border-t border-slate-200">
                      <td className={cell}>{i.stock_item_name}</td>
                      <td className={`${cell} text-right tabular-nums`}>
                        {i.quantity ? formatQuantity(i.quantity) : ""} {i.unit ?? ""}
                      </td>
                      <td className={`${cell} text-right`}>
                        {i.rate ? <Money value={i.rate} /> : ""}
                      </td>
                      <td className={`${cell} text-right`}>
                        {i.amount ? <Money value={i.amount} /> : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </ScrollableTable>
            )}
            {v.custom_fields.length > 0 && (
              <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
                {v.custom_fields.map((f) => (
                  <div key={f.field_key} className="contents">
                    <dt className="text-slate-600">{humanize(f.field_key)}</dt>
                    <dd>{String(f.value ?? "")}</dd>
                  </div>
                ))}
              </dl>
            )}
            {can(company, "VIEW_LOGS") && <History voucherId={v.voucher_id} />}
          </>
        )}
      </Loaded>
    </section>
  );
}

function History({ voucherId }: { voucherId: string }) {
  const company = useCompany();
  const query = useCompanyQuery<Schemas["AuditEntryOut"][]>("/audit", {
    query: { entity_type: "voucher", entity_id: voucherId },
  });
  return (
    <section className="space-y-2">
      <h2 className="font-semibold">History</h2>
      <Loaded query={query} label="Loading the history">
        {(entries) =>
          entries.length === 0 ? (
            <p className="text-sm text-slate-600">No changes since it was first synced.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {entries.map((e) => (
                <li key={e.id}>
                  <TimeText value={e.created_at} timeZone={company.company_timezone} /> {e.action}
                  {e.after && (
                    <span className="block break-words text-slate-600">
                      {Object.entries(e.after)
                        .map(([k, value]) => `${k}: ${JSON.stringify(value)}`)
                        .join("; ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </section>
  );
}
