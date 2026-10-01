import { useState, type FormEvent } from "react";
import type { Schemas } from "../api/types";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge, EmptyState, TimeText } from "../components/ui";
import { useCompany } from "../lib/company";
import { describeCron } from "../lib/cron";
import { ErrorText, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";

type Schedule = Schemas["ScheduleOut"];
type SyncMode = Schemas["SyncMode"];
const cell = "px-3 py-2 text-left align-top";
const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-2";

/** Plain words for a cron expression, always naming the company's time zone (TZ-1.1). */
export function CronPreview({ expression }: { expression: string }) {
  const tz = useCompany().company_timezone;
  const words = describeCron(expression);
  return (
    <span className="text-sm text-slate-700">
      {words ?? `Custom schedule: ${expression}`} (company time, {tz})
    </span>
  );
}

/** RTE-1.3: the company's schedules (Owner and Admin). */
export function Schedules() {
  const tz = useCompany().company_timezone;
  const schedules = useCompanyQuery<Schedule[]>("/sync-schedules");
  const [editing, setEditing] = useState<string | null>(null);
  const toggle = useCompanyAction<Schedule, Schedule>((s) => ({
    path: `/sync-schedules/${s.schedule_id}`,
    method: "PUT",
    body: { is_active: !s.is_active },
  }));
  return (
    <div className="space-y-2">
      <h2 className="font-semibold">Schedules</h2>
      <ErrorText error={toggle.error} />
      <Loaded query={schedules} label="Loading schedules">
        {(list) =>
          list.length === 0 ? (
            <EmptyState>No schedule yet: syncs run only when someone presses Sync Now.</EmptyState>
          ) : (
            <ScrollableTable caption="Sync schedules">
              <thead className="bg-slate-50">
                <tr>
                  <th className={cell}>When</th>
                  <th className={cell}>Agent</th>
                  <th className={cell}>Mode</th>
                  <th className={cell}>Next run</th>
                  <th className={cell}>State</th>
                  <th className={cell}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.map((s) =>
                  editing === s.schedule_id ? (
                    <tr key={s.schedule_id} className="border-t border-slate-200">
                      <td colSpan={6} className={cell}>
                        <ScheduleForm schedule={s} onDone={() => setEditing(null)} />
                      </td>
                    </tr>
                  ) : (
                    <tr key={s.schedule_id} className="border-t border-slate-200">
                      <td className={cell}>
                        <code className="block">{s.cron_expression}</code>
                        <CronPreview expression={s.cron_expression} />
                      </td>
                      <td className={cell}>{s.agent_name}</td>
                      <td className={cell}>{s.sync_mode}</td>
                      <td className={cell}>
                        <TimeText value={s.next_fire_at} timeZone={tz} />
                      </td>
                      <td className={cell}>
                        <Badge tone={s.is_active ? "ok" : "neutral"}>
                          {s.is_active ? "Active" : "Paused"}
                        </Badge>
                      </td>
                      <td className={`${cell} whitespace-nowrap`}>
                        <button
                          type="button"
                          className="underline"
                          onClick={() => setEditing(s.schedule_id)}
                        >
                          Edit
                        </button>{" "}
                        <button
                          type="button"
                          className="underline"
                          onClick={() => toggle.mutate(s)}
                        >
                          {s.is_active ? "Pause" : "Activate"}
                        </button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </ScrollableTable>
          )
        }
      </Loaded>
      {editing === null && <ScheduleForm />}
    </div>
  );
}

/** Create a schedule, or edit one (the Agent of a schedule is fixed once created). */
function ScheduleForm({ schedule, onDone }: { schedule?: Schedule; onDone?: () => void }) {
  const agents = useCompanyQuery<Schemas["AgentsView"]>("/agents");
  const [cron, setCron] = useState(schedule?.cron_expression ?? "0 2 * * *");
  const [mode, setMode] = useState<SyncMode>(schedule?.sync_mode ?? "INCREMENTAL");
  const [agentId, setAgentId] = useState(schedule?.agent_id ?? "");
  const [active, setActive] = useState(schedule?.is_active ?? true);
  const save = useCompanyAction<Schedule>(() =>
    schedule
      ? {
          path: `/sync-schedules/${schedule.schedule_id}`,
          method: "PUT",
          body: { cron_expression: cron.trim(), sync_mode: mode, is_active: active },
        }
      : {
          path: "/sync-schedules",
          body: {
            agent_id: agentId,
            cron_expression: cron.trim(),
            sync_mode: mode,
            is_active: active,
          },
        },
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(undefined, { onSuccess: () => onDone?.() });
  }
  const usable = (agents.data?.agents ?? []).filter((a) => a.status !== "REVOKED");
  return (
    <form onSubmit={submit} className="grid gap-2 rounded bg-slate-50 p-3 sm:grid-cols-2">
      <h3 className="font-medium sm:col-span-2">{schedule ? "Edit schedule" : "New schedule"}</h3>
      {!schedule && (
        <label className="text-sm">
          Agent
          <select
            required
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className={input}
          >
            <option value="">Choose an Agent</option>
            {usable.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.agent_name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="text-sm">
        Mode
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as SyncMode)}
          className={input}
        >
          <option value="INCREMENTAL">Changes since the last sync</option>
          <option value="FULL">Full sync</option>
          <option value="RECONCILIATION">Reconciliation with Tally</option>
        </select>
      </label>
      <label className="text-sm sm:col-span-2">
        Cron expression (minute hour day month weekday)
        <input
          required
          value={cron}
          onChange={(e) => setCron(e.target.value)}
          className={`${input} font-mono`}
        />
      </label>
      <p className="sm:col-span-2">
        <CronPreview expression={cron} />
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active
      </label>
      <div className="space-y-1 sm:col-span-2">
        <ErrorText error={save.error} />
        <div className="flex gap-2">
          <button type="submit" className="rounded bg-slate-800 px-3 py-1 text-white">
            {schedule ? "Save" : "Add schedule"}
          </button>
          {onDone && (
            <button type="button" className="rounded px-3 py-1" onClick={onDone}>
              Cancel
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
