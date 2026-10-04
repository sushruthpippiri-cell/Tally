import { Link } from "react-router-dom";
import type { Schemas } from "../api/types";
import { Badge, TimeText } from "../components/ui";
import { Warnings } from "../components/Warnings";
import { can, useCompany } from "../lib/company";
import { Loaded, useCompanyQuery } from "../lib/queries";
import { OVERALL_TONE } from "./ReconciliationPage";
import { RunBadge } from "./SyncPage";

const card = "space-y-2 rounded border border-slate-200 bg-white p-3";

/** P13.10: last sync, reconciliation and Agent health, with every warning they carry. The full
 * home dashboard arrives in P14. */
export function HomePage() {
  const company = useCompany();
  const tz = company.company_timezone;
  const status = useCompanyQuery<Schemas["SyncStatusOut"]>("/sync/status");
  const agents = useCompanyQuery<Schemas["AgentsView"]>("/agents");
  const base = `/c/${company.company_id}`;
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Home</h1>
      <div className="grid gap-3 md:grid-cols-3">
        <Loaded query={status} label="Loading sync status">
          {(s) => (
            <>
              <div className={card}>
                <h2 className="font-semibold">Last sync</h2>
                {s.last_run ? (
                  <p className="text-sm">
                    <RunBadge status={s.last_run.status} />{" "}
                    <TimeText value={s.last_run.ended_at ?? s.last_run.started_at} timeZone={tz} />
                  </p>
                ) : (
                  <p className="text-sm">No sync has run yet.</p>
                )}
                <Warnings warnings={s.warnings} />
                {can(company, "RUN_SYNC") && (
                  <Link to={`${base}/sync`} className="text-sm underline">
                    Go to Sync
                  </Link>
                )}
              </div>
              <div className={card}>
                <h2 className="font-semibold">Reconciliation</h2>
                {s.reconciliation ? (
                  <p className="text-sm">
                    <Badge tone={OVERALL_TONE[s.reconciliation.overall]}>
                      {s.reconciliation.overall}
                    </Badge>{" "}
                    <TimeText value={s.reconciliation.run_at} timeZone={tz} />
                  </p>
                ) : (
                  <p className="text-sm">Not run yet.</p>
                )}
                {s.reconciliation && s.reconciliation.overall !== "PASS" && (
                  <p role="alert" className="text-sm text-red-800">
                    {s.reconciliation.overall === "FAIL"
                      ? "Figures here differ from Tally's beyond the tolerance."
                      : "Some figures could not be compared with Tally."}
                  </p>
                )}
                {can(company, "VIEW_RECON_AND_DQ") && (
                  <Link to={`${base}/reconciliation`} className="text-sm underline">
                    See the comparison
                  </Link>
                )}
              </div>
            </>
          )}
        </Loaded>
        <Loaded query={agents} label="Loading Agents">
          {(a) => {
            const counts = Object.entries(
              a.agents.reduce<Record<string, number>>(
                (all, x) => ({ ...all, [x.status]: (all[x.status] ?? 0) + 1 }),
                {},
              ),
            );
            const restart = a.agents.filter((x) => x.uptime_advisory !== "none");
            return (
              <div className={card}>
                <h2 className="font-semibold">Agents</h2>
                <p className="flex flex-wrap gap-1 text-sm">
                  {counts.length === 0
                    ? "No Agent registered."
                    : counts.map(([s, n]) => (
                        <Badge key={s} tone={s === "ACTIVE" ? "ok" : "warn"}>{`${n} ${s}`}</Badge>
                      ))}
                </p>
                {restart.map((x) => (
                  <p
                    key={x.agent_id}
                    role="alert"
                    className={`text-sm ${x.uptime_advisory === "prominent" ? "text-red-800" : "text-amber-900"}`}
                  >
                    Restart recommended on {x.agent_name}
                    {x.uptime_advisory === "prominent"
                      ? ": the latest reconciliation failed."
                      : "."}
                  </p>
                ))}
                <Warnings
                  warnings={[
                    ...a.warnings,
                    ...a.agents.flatMap((x) => x.warnings.map((w) => `${x.agent_name}: ${w}`)),
                  ]}
                />
                <Link to={`${base}/agents`} className="text-sm underline">
                  See Agents
                </Link>
              </div>
            );
          }}
        </Loaded>
      </div>
    </section>
  );
}
