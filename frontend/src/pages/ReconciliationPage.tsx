import { useState } from "react";
import { ApiError } from "../api/client";
import type { Schemas } from "../api/types";
import { Money } from "../components/Money";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge, DateText, EmptyState, TimeText } from "../components/ui";
import { Warnings } from "../components/Warnings";
import { can, useCompany } from "../lib/company";
import { ErrorText, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";
import { AgentChoice } from "./SyncPage";

type Recon = Schemas["ReconciliationOut"];
type Row = Schemas["ReconciliationRow"];
const PAGE = 100;
const cell = "px-3 py-2 text-left align-top";
export const OVERALL_TONE = { PASS: "ok", FAIL: "bad", INCOMPLETE: "warn" } as const;

const METRICS: Record<string, string> = {
  SALES_CREDITS: "Sales",
  PURCHASE_DEBITS: "Purchases",
  RECEIPTS: "Receipts",
  PAYMENTS: "Payments",
  LEDGER_BALANCE: "Ledger balance",
  STOCK_QTY: "Closing stock quantity",
  TOTALS: "Voucher totals",
};

/** A value as the backend sent it: money with ₹, a quantity as it is. */
function Amount({ metric, value }: { metric: string; value: string }) {
  return metric === "STOCK_QTY" ? (
    <span className="whitespace-nowrap">{value}</span>
  ) : (
    <Money value={value} />
  );
}

/** The independent comparison with Tally's own figures (SRS 9). Every difference shown is the
 * backend's; nothing is subtracted here. */
export function ReconciliationPage() {
  const company = useCompany();
  const [runId, setRunId] = useState<string | null>(null);
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const recon = useCompanyQuery<Recon>("/reconciliation", {
    query: { run_id: runId, only_failures: failuresOnly, offset, limit: PAGE },
  });
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Reconciliation</h1>
      {can(company, "RUN_SYNC") && <RunReconciliation />}
      <Loaded query={recon} label="Loading reconciliation">
        {(r) =>
          r.run === null ? (
            <EmptyState>No reconciliation has run yet.</EmptyState>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={OVERALL_TONE[r.run.overall]}>{r.run.overall}</Badge>
                <span className="text-sm">
                  As of <DateText value={r.run.as_of} />, run{" "}
                  <TimeText value={r.run.run_at} timeZone={company.company_timezone} /> ·{" "}
                  {r.run.compared} compared · {r.run.failed} failed
                </span>
              </div>
              <Warnings
                unverifiedGates={r.unverified_gates}
                warnings={
                  r.run.overall === "INCOMPLETE"
                    ? [
                        "Incomplete: some figures could not be compared (listed below), so this run cannot pass.",
                      ]
                    : []
                }
              />
              {r.history.length > 1 && (
                <label className="block text-sm">
                  Run
                  <select
                    className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 sm:w-auto"
                    value={runId ?? r.run.sync_run_id}
                    onChange={(e) => {
                      setRunId(e.target.value);
                      setOffset(0);
                    }}
                  >
                    {r.history.map((h) => (
                      <option key={h.sync_run_id} value={h.sync_run_id}>
                        {h.as_of} · {h.overall} · {h.failed} failed
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {r.not_compared.length > 0 && <NotCompared items={r.not_compared} />}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={failuresOnly}
                  onChange={(e) => {
                    setFailuresOnly(e.target.checked);
                    setOffset(0);
                  }}
                />
                Failures only
              </label>
              <Rows rows={r.rows} />
              <div className="flex items-center gap-3 text-sm">
                <span>
                  {r.total_rows === 0 ? 0 : offset + 1}–{offset + r.rows.length} of {r.total_rows}
                </span>
                <button
                  type="button"
                  className="underline disabled:opacity-40"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="underline disabled:opacity-40"
                  disabled={offset + r.rows.length >= r.total_rows}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next
                </button>
              </div>
            </div>
          )
        }
      </Loaded>
    </section>
  );
}

function Rows({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return <EmptyState>Nothing to show.</EmptyState>;
  return (
    <ScrollableTable caption="Comparisons with Tally">
      <thead className="bg-slate-50">
        <tr>
          <th className={cell}>What</th>
          <th className={cell}>Period</th>
          <th className={`${cell} text-right`}>Tally</th>
          <th className={`${cell} text-right`}>Here</th>
          <th className={`${cell} text-right`}>Difference</th>
          <th className={`${cell} text-right`}>Difference %</th>
          <th className={cell}>Result</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="border-t border-slate-200">
            <td className={cell}>
              {METRICS[row.metric] ?? row.metric}
              {row.entity_name && (
                <span className="block break-all text-slate-600">{row.entity_name}</span>
              )}
            </td>
            <td className={cell}>
              <DateText value={row.period_start} /> – <DateText value={row.period_end} />
            </td>
            <td className={`${cell} text-right`}>
              <Amount metric={row.metric} value={row.tally_value} />
            </td>
            <td className={`${cell} text-right`}>
              <Amount metric={row.metric} value={row.local_value} />
            </td>
            <td className={`${cell} text-right`}>
              <Amount metric={row.metric} value={row.absolute_difference} />
            </td>
            <td className={`${cell} text-right`}>
              {row.percentage_difference === null ? "—" : `${row.percentage_difference}%`}
            </td>
            <td className={cell}>
              <Badge tone={row.result === "PASS" ? "ok" : "bad"}>{row.result}</Badge>
            </td>
          </tr>
        ))}
      </tbody>
    </ScrollableTable>
  );
}

function NotCompared({ items }: { items: Schemas["NotCompared"][] }) {
  return (
    <div className="space-y-1">
      <h2 className="font-semibold">Not compared</h2>
      <ScrollableTable caption="Figures that could not be compared">
        <thead className="bg-slate-50">
          <tr>
            <th className={cell}>What</th>
            <th className={cell}>Item</th>
            <th className={cell}>Why</th>
            <th className={cell}>Effect</th>
          </tr>
        </thead>
        <tbody>
          {items.map((n, i) => (
            <tr key={i} className="border-t border-slate-200">
              <td className={cell}>{METRICS[n.metric] ?? n.metric}</td>
              <td className={`${cell} break-all`}>{n.name ?? n.entity_guid}</td>
              <td className={cell}>{n.reason}</td>
              <td className={cell}>
                <Badge tone={n.fails ? "bad" : "warn"}>
                  {n.fails ? "Counts as a failure" : "Not compared"}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </ScrollableTable>
    </div>
  );
}

function RunReconciliation() {
  const agents = useCompanyQuery<Schemas["AgentsView"]>("/agents");
  const [agentId, setAgentId] = useState("");
  const run = useCompanyAction<Schemas["CommandStatusOut"]>(() => ({
    path: "/reconciliation/run",
    body: { agent_id: agentId || null },
  }));
  const forced = run.error instanceof ApiError && run.error.code === "AGENT_SELECTION_REQUIRED";
  return (
    <form
      aria-label="Run reconciliation"
      className="space-y-2 rounded border border-slate-200 bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        run.mutate();
      }}
    >
      <AgentChoice
        agents={agents.data?.agents ?? []}
        value={agentId}
        onChange={setAgentId}
        forced={forced}
      />
      <ErrorText error={run.error} />
      {run.isSuccess && (
        <p role="status" className="text-sm text-green-800">
          Reconciliation requested; the Agent picks it up on its next poll. Follow it on the Sync
          page.
        </p>
      )}
      <button
        type="submit"
        disabled={run.isPending}
        className="rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-50"
      >
        Run reconciliation
      </button>
    </form>
  );
}
