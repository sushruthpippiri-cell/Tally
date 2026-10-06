import { useState } from "react";
import { Link } from "react-router-dom";
import type { Schemas } from "../api/types";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { Warnings } from "../components/Warnings";
import { Badge, DateText, EmptyState } from "../components/ui";
import { useCompany } from "../lib/company";
import { ErrorText, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";

type Anomaly = Schemas["AnomalyOut"];

/** FR-3.7: the evidence the application computed and whatever Claude wrote about it are two
 * clearly separate, clearly labelled areas. Nothing on this page is computed in the browser. */
function Evidence({ a }: { a: Anomaly }) {
  const rows: [string, React.ReactNode][] = [
    ["Transaction amount", a.transaction_amount ? <Money value={a.transaction_amount} /> : "—"],
    ["This party's average", a.historical_average ? <Money value={a.historical_average} /> : "—"],
    ["Highest before this", a.historical_max ? <Money value={a.historical_max} /> : "—"],
    ["Above average by", a.deviation_display ?? "—"],
  ];
  return (
    <section aria-label="Evidence" className="rounded border border-slate-300 p-3">
      <h4 className="mb-2 text-sm font-semibold">Evidence — measured by this system</h4>
      {/* A plain list, not a grid: a twenty-digit figure in a fixed second column overflowed the
          panel at 360 px and covered the review buttons below it (NFR-UI-1). Here the value
          wraps inside its own row and nothing can escape the panel. */}
      <dl className="space-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-wrap items-baseline justify-between gap-x-4">
            <dt className="text-slate-600">{label}</dt>
            <dd className="font-medium break-words">{value}</dd>
          </div>
        ))}
      </dl>
      {a.duplicate_of_voucher_id && (
        <p className="mt-2 text-sm">
          Possible duplicate of voucher {a.duplicate_of_voucher_number ?? ""} dated{" "}
          <DateText value={a.duplicate_of_voucher_date} />.
        </p>
      )}
    </section>
  );
}

const UNAVAILABLE: Record<string, string> = {
  NOT_CONFIGURED: "No explanation: the AI explainer is not configured for this server.",
  CLAUDE_UNREACHABLE: "No explanation: Claude could not be reached. The evidence above stands.",
  TIMEOUT: "No explanation: the request to Claude timed out. The evidence above stands.",
  REFUSED: "No explanation: Claude declined to answer. The evidence above stands.",
  NUMBER_NOT_IN_EVIDENCE:
    "No explanation: the one Claude wrote contained a figure that is not in the evidence, so it " +
    "was discarded.",
};

function Explanation({ a }: { a: Anomaly }) {
  return (
    <section
      aria-label="Explanation"
      className="min-w-0 rounded border border-sky-300 bg-sky-50 p-3"
    >
      <h4 className="mb-2 text-sm font-semibold">
        Explanation — written by Claude from the evidence
      </h4>
      {a.explanation_status === "AVAILABLE" && a.explanation_text ? (
        <p className="text-sm whitespace-pre-line">{a.explanation_text}</p>
      ) : a.explanation_status === "PENDING" ? (
        <p className="text-sm text-slate-600">Not written yet.</p>
      ) : (
        <Warnings
          warnings={[
            UNAVAILABLE[a.explanation_unavailable_reason ?? ""] ??
              "No explanation is available. The evidence above stands.",
          ]}
        />
      )}
    </section>
  );
}

/** The selected anomaly's detail, below the table rather than inside it: a very long party name
 * in a wide table overlapped the buttons at 360 px, and reaching them meant scrolling sideways. */
function Details({ a, canReview }: { a: Anomaly; canReview: boolean }) {
  const company = useCompany();
  const review = useCompanyAction<Anomaly, Schemas["ReviewRequest"]>((body) => ({
    path: `/anomalies/${a.anomaly_id}/review`,
    method: "POST",
    body,
  }));
  const current = review.data ?? a;
  return (
    <section aria-label="Anomaly detail" className="space-y-3 rounded border border-slate-300 p-3">
      <h3 className="text-sm font-semibold">
        {current.party_name ?? "Unknown party"} — voucher {current.voucher_number ?? ""} dated{" "}
        <DateText value={current.voucher_date} />
      </h3>
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <Evidence a={current} />
        <Explanation a={current} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Link to={`/c/${company.company_id}/vouchers/${current.voucher_id}`} className="underline">
          Open the voucher
        </Link>
        {canReview && !current.reviewed && (
          <>
            <button
              type="button"
              className="rounded border border-slate-300 bg-white px-3 py-1"
              disabled={review.isPending}
              onClick={() => review.mutate({ action: "reviewed" })}
            >
              Mark reviewed
            </button>
            <button
              type="button"
              className="rounded border border-slate-300 bg-white px-3 py-1"
              disabled={review.isPending}
              onClick={() => review.mutate({ action: "not_an_issue" })}
            >
              Not an issue
            </button>
          </>
        )}
        <ErrorText error={review.error} />
      </div>
    </section>
  );
}

/** SRS 12: flagged transactions, their evidence, and - separately - the explanation. */
export function AnomaliesPage() {
  const company = useCompany();
  const [unreviewed, setUnreviewed] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const query = useCompanyQuery<Schemas["AnomaliesOut"]>("/anomalies", {
    query: unreviewed ? { reviewed: false } : {},
  });
  const canReview = company.my_permissions.includes("REVIEW_ANOMALIES");
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Anomalies</h1>
      <p className="text-sm text-slate-700">
        Found by this system&apos;s own rules. No figure on this page comes from Claude; where an
        explanation exists it is shown separately, and it uses only the figures beside it.
      </p>
      <Loaded query={query} label="Loading anomalies">
        {(a) =>
          !a.available ? (
            <EmptyState>{a.reason ?? "Anomaly detection is off for this company."}</EmptyState>
          ) : (
            <div className="space-y-4">
              {!a.explanations_configured && a.anomalies.length > 0 && (
                <Warnings
                  notes={[
                    "Written explanations are not configured on this server, so none will be " +
                      "requested. Every figure below is measured here and is unaffected.",
                  ]}
                />
              )}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={unreviewed}
                  onChange={(e) => setUnreviewed(e.target.checked)}
                />
                Show only the ones nobody has reviewed
              </label>
              {a.anomalies.length === 0 ? (
                <EmptyState>Nothing flagged.</EmptyState>
              ) : (
                <>
                  <ScrollableTable caption={`${a.total_count} flagged transactions`}>
                    <thead className="bg-slate-100">
                      <tr>
                        <th className="px-3 py-2">Date</th>
                        <th className="px-3 py-2">Party</th>
                        <th className="px-3 py-2 text-right">Amount</th>
                        <th className="px-3 py-2">Why it was flagged</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2">
                          <span className="sr-only">Details</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.anomalies.map((row) => (
                        <tr key={row.anomaly_id} className="border-t border-slate-200">
                          <td className="px-3 py-2">
                            <DateText value={row.voucher_date} />
                          </td>
                          <td className="px-3 py-2">{row.party_name ?? "—"}</td>
                          <td className="px-3 py-2 text-right">
                            {row.transaction_amount ? (
                              <Money value={row.transaction_amount} />
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="px-3 py-2">{row.rule_label}</td>
                          <td className="px-3 py-2">
                            {row.not_an_issue ? (
                              <Badge tone="neutral">Not an issue</Badge>
                            ) : row.reviewed ? (
                              <Badge tone="ok">Reviewed</Badge>
                            ) : (
                              <Badge tone="warn">New</Badge>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              aria-expanded={selected === row.anomaly_id}
                              className="underline"
                              onClick={() =>
                                setSelected(selected === row.anomaly_id ? null : row.anomaly_id)
                              }
                            >
                              Details
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </ScrollableTable>
                  {(() => {
                    const chosen = a.anomalies.find((r) => r.anomaly_id === selected);
                    return chosen ? (
                      <Details key={chosen.anomaly_id} a={chosen} canReview={canReview} />
                    ) : null;
                  })()}
                </>
              )}
            </div>
          )
        }
      </Loaded>
    </section>
  );
}
