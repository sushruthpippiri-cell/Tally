import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import type { Schemas } from "../api/types";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge, EmptyState, TimeText } from "../components/ui";
import { Warnings } from "../components/Warnings";
import { can, useCompany } from "../lib/company";
import { messageForCode } from "../lib/errorMessages";
import { ErrorText, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";
import { Schedules } from "./Schedules";

type Command = Schemas["CommandStatusOut"];
type Agent = Schemas["AgentOut"];
type SyncMode = Schemas["SyncMode"];

export const POLL_MS = 3000;
const TERMINAL = new Set(["COMPLETED", "FAILED", "EXPIRED", "FAILED_AGENT_LOST"]);
const MODES: { value: SyncMode; label: string }[] = [
  { value: "INCREMENTAL", label: "Changes since the last sync" },
  { value: "FULL", label: "Full sync" },
  { value: "DATE_RANGE", label: "A date range" },
  { value: "RECONCILIATION", label: "Reconciliation with Tally" },
];
const cell = "px-3 py-2 text-left align-top";

export function SyncPage() {
  const company = useCompany();
  const [command, setCommand] = useState<string | null>(null);
  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Sync</h1>
      <SyncNow onSent={setCommand} />
      {command && <Timeline commandId={command} />}
      <SyncStatus />
      <Runs />
      {can(company, "VIEW_LOGS") && <Errors />}
      {can(company, "MANAGE_SCHEDULES") && <Schedules />}
    </section>
  );
}

/** Agents a command can go to, and whether the user must choose (mirrors the API's routing:
 * one eligible Agent, or exactly one ACTIVE among several, is chosen for them; RTE-1.1/1.2). */
export function routing(agents: readonly Agent[]) {
  const eligible = agents.filter((a) => a.status !== "REVOKED" && a.status !== "INCOMPATIBLE");
  const active = eligible.filter((a) => a.status === "ACTIVE");
  const automatic = eligible.length === 1 ? eligible[0] : active.length === 1 ? active[0] : null;
  return { eligible, automatic: automatic ?? null, mustChoose: eligible.length > 1 && !automatic };
}

/** The Agent selector shared by Sync Now and Run reconciliation. */
export function AgentChoice({
  agents,
  value,
  onChange,
  forced,
}: {
  agents: readonly Agent[];
  value: string;
  onChange: (id: string) => void;
  forced: boolean;
}) {
  const { eligible, automatic, mustChoose } = routing(agents);
  if (eligible.length <= 1 && !forced) return null;
  return (
    <label className="block text-sm">
      Agent
      <select
        required={mustChoose || forced}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 block w-full rounded border border-slate-300 px-2 py-2"
      >
        <option value="">
          {mustChoose || forced || !automatic
            ? "Choose an Agent"
            : `Automatic (${automatic.agent_name})`}
        </option>
        {eligible.map((a) => (
          <option key={a.agent_id} value={a.agent_id}>
            {a.agent_name} ({a.status})
          </option>
        ))}
      </select>
    </label>
  );
}

function SyncNow({ onSent }: { onSent: (commandId: string) => void }) {
  const agents = useCompanyQuery<Schemas["AgentsView"]>("/agents");
  const [mode, setMode] = useState<SyncMode>("INCREMENTAL");
  const [agentId, setAgentId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const send = useCompanyAction<Command, Schemas["CompanySyncRequest"]>((body) => ({
    path: "/sync",
    body,
  }));
  // The API asked for a choice (RTE-1.2) even if the list we hold suggested otherwise.
  const forced = send.error instanceof ApiError && send.error.code === "AGENT_SELECTION_REQUIRED";

  function submit(event: FormEvent) {
    event.preventDefault();
    send.mutate(
      {
        sync_mode: mode,
        agent_id: agentId || null,
        date_from: mode === "DATE_RANGE" ? from : null,
        date_to: mode === "DATE_RANGE" ? to : null,
      },
      { onSuccess: (c) => onSent(c.command_id) },
    );
  }
  const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-2";
  return (
    <form
      onSubmit={submit}
      aria-labelledby="sync-now"
      className="space-y-3 rounded border border-slate-200 bg-white p-3"
    >
      <h2 id="sync-now" className="font-semibold">
        Sync now
      </h2>
      <AgentChoice
        agents={agents.data?.agents ?? []}
        value={agentId}
        onChange={setAgentId}
        forced={forced}
      />
      <label className="block text-sm">
        What to sync
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as SyncMode)}
          className={input}
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      {mode === "DATE_RANGE" && (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">
            From
            <input
              type="date"
              required
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className={input}
            />
          </label>
          <label className="text-sm">
            To
            <input
              type="date"
              required
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className={input}
            />
          </label>
        </div>
      )}
      <ErrorText error={send.error} />
      <button
        type="submit"
        disabled={send.isPending || agents.isPending}
        className="rounded bg-slate-800 px-4 py-2 text-white disabled:opacity-50"
      >
        Sync Now
      </button>
    </form>
  );
}

const STEPS = ["PENDING", "CLAIMED", "RUNNING"] as const;

/** AGT-1.6 / AC-17: the command's state as it changes, polled every 3 s until it ends. */
export function Timeline({ commandId }: { commandId: string }) {
  const tz = useCompany().company_timezone;
  const query = useCompanyQuery<Command>(`/commands/${commandId}`, {
    poll: (c) => (c && TERMINAL.has(c.status) ? false : POLL_MS),
  });
  return (
    <Loaded query={query} label="Loading the sync">
      {(c) => {
        const reached = TERMINAL.has(c.status)
          ? 3
          : STEPS.indexOf(c.status as (typeof STEPS)[number]);
        const times: Record<string, string | null> = {
          PENDING: c.created_at,
          CLAIMED: c.claimed_at,
          RUNNING: null,
        };
        const final = TERMINAL.has(c.status) ? c.status : "COMPLETED";
        return (
          <div
            className="space-y-2 rounded border border-slate-200 bg-white p-3"
            aria-live="polite"
          >
            <h2 className="font-semibold">
              {c.sync_mode} sync on {c.agent_name}
            </h2>
            {c.waiting_label && (
              <p
                role="alert"
                className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              >
                {c.waiting_label}
              </p>
            )}
            <ol aria-label="Sync progress" className="flex flex-wrap gap-2 text-sm">
              {[...STEPS, final].map((step, i) => (
                <li
                  key={step}
                  aria-current={i === reached || (i === 3 && reached === 3) ? "step" : undefined}
                  className={`rounded px-2 py-1 ${i <= reached ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-500"}`}
                >
                  {step}
                  {i < 3 && times[step] && i <= reached && (
                    <span className="ml-1 opacity-80">
                      <TimeText value={times[step]} timeZone={tz} />
                    </span>
                  )}
                  {i === 3 && reached === 3 && c.completed_at && (
                    <span className="ml-1 opacity-80">
                      <TimeText value={c.completed_at} timeZone={tz} />
                    </span>
                  )}
                </li>
              ))}
            </ol>
            {c.error_code && (
              <p role="alert" className="text-sm text-red-800">
                {messageForCode(c.error_code)}
                {c.error_message && ` (${c.error_message})`}
              </p>
            )}
          </div>
        );
      }}
    </Loaded>
  );
}

function SyncStatus() {
  const tz = useCompany().company_timezone;
  const status = useCompanyQuery<Schemas["SyncStatusOut"]>("/sync/status");
  return (
    <Loaded query={status} label="Loading sync status">
      {(s) => (
        <div className="space-y-2">
          <h2 className="font-semibold">Status</h2>
          <Warnings warnings={s.warnings} />
          {s.last_run && (
            <p className="text-sm">
              Last sync: <RunBadge status={s.last_run.status} /> started{" "}
              <TimeText value={s.last_run.started_at} timeZone={tz} />, {s.last_run.records_fetched}{" "}
              records, {s.last_run.records_failed} failed
            </p>
          )}
          <ScrollableTable caption="Collections">
            <thead className="bg-slate-50">
              <tr>
                <th className={cell}>Collection</th>
                <th className={cell}>Mode</th>
                <th className={cell}>Status</th>
                <th className={cell}>Watermark</th>
                <th className={cell}>Last success</th>
                <th className={cell}>Lease</th>
              </tr>
            </thead>
            <tbody>
              {s.collections.map((c) => (
                <tr key={c.collection_type} className="border-t border-slate-200">
                  <td className={cell}>{c.collection_type}</td>
                  <td className={cell}>
                    <Badge tone={c.mode === "FULL_ONLY" ? "warn" : "neutral"}>{c.label}</Badge>
                  </td>
                  <td className={cell}>
                    {c.status}
                    {c.held_back > 0 && (
                      <span role="alert" className="block text-amber-900">
                        Held back by {c.held_back} failing record{c.held_back === 1 ? "" : "s"}
                      </span>
                    )}
                  </td>
                  <td className={cell}>{c.watermark}</td>
                  <td className={cell}>
                    <TimeText value={c.last_successful_sync_at} timeZone={tz} />
                  </td>
                  <td className={cell}>
                    {c.lease_holder ? (
                      <>
                        {c.lease_holder} until <TimeText value={c.lease_expires_at} timeZone={tz} />
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </ScrollableTable>
        </div>
      )}
    </Loaded>
  );
}

export function RunBadge({ status }: { status: string }) {
  const tone =
    status === "COMPLETED"
      ? "ok"
      : status === "RUNNING"
        ? "neutral"
        : status === "PARTIAL"
          ? "warn"
          : "bad";
  return <Badge tone={tone}>{status}</Badge>;
}

function Runs() {
  const tz = useCompany().company_timezone;
  const runs = useCompanyQuery<Schemas["RunSummary"][]>("/sync/runs", { query: { limit: 20 } });
  return (
    <div className="space-y-2">
      <h2 className="font-semibold">Recent runs</h2>
      <Loaded query={runs} label="Loading runs">
        {(list) =>
          list.length === 0 ? (
            <EmptyState>No sync has run yet.</EmptyState>
          ) : (
            <ScrollableTable caption="Recent sync runs">
              <thead className="bg-slate-50">
                <tr>
                  <th className={cell}>Started</th>
                  <th className={cell}>Mode</th>
                  <th className={cell}>Result</th>
                  <th className={cell}>Records</th>
                  <th className={cell}>Failed</th>
                  <th className={cell}>Ended</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.sync_run_id} className="border-t border-slate-200">
                    <td className={cell}>
                      <TimeText value={r.started_at} timeZone={tz} />
                    </td>
                    <td className={cell}>{r.sync_mode}</td>
                    <td className={cell}>
                      <RunBadge status={r.status} />
                    </td>
                    <td className={cell}>{r.records_fetched}</td>
                    <td className={cell}>{r.records_failed}</td>
                    <td className={cell}>
                      <TimeText value={r.ended_at} timeZone={tz} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
          )
        }
      </Loaded>
    </div>
  );
}

function Errors() {
  const tz = useCompany().company_timezone;
  const errors = useCompanyQuery<Schemas["SyncErrorOut"][]>("/sync/errors", {
    query: { limit: 50 },
  });
  return (
    <div className="space-y-2">
      <h2 className="font-semibold">Sync errors</h2>
      <Loaded query={errors} label="Loading sync errors">
        {(list) =>
          list.length === 0 ? (
            <EmptyState>No sync errors.</EmptyState>
          ) : (
            <ScrollableTable caption="Sync errors, newest first">
              <thead className="bg-slate-50">
                <tr>
                  <th className={cell}>When</th>
                  <th className={cell}>Code</th>
                  <th className={cell}>Record</th>
                  <th className={cell}>ALTERID</th>
                  <th className={cell}>Message</th>
                </tr>
              </thead>
              <tbody>
                {list.map((e) => (
                  <tr key={e.id} className="border-t border-slate-200">
                    <td className={cell}>
                      <TimeText value={e.created_at} timeZone={tz} />
                    </td>
                    <td className={cell}>{e.error_code}</td>
                    <td className={`${cell} break-all`}>
                      {e.entity_type} {e.tally_guid ?? ""}
                    </td>
                    <td className={cell}>{e.alter_id ?? "—"}</td>
                    <td className={cell}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
          )
        }
      </Loaded>
    </div>
  );
}
