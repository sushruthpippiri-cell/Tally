import { useState, type FormEvent } from "react";
import type { Schemas } from "../api/types";
import { Badge, ConfirmDialog, EmptyState, SecretOnce, TimeText } from "../components/ui";
import { Warnings } from "../components/Warnings";
import { can, useCompany } from "../lib/company";
import { messageForCode } from "../lib/errorMessages";
import { toInt } from "../lib/integers";
import { ErrorText, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";

type Agent = Schemas["AgentOut"];
type Queue = Schemas["QueueStatus"];

const STATUS_TONE = {
  ACTIVE: "ok",
  REGISTERING: "neutral",
  OFFLINE: "warn",
  INCOMPATIBLE: "bad",
  REVOKED: "neutral",
} as const;

function duration(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days > 0 ? `${days} d ${hours} h` : `${hours} h ${Math.floor((seconds % 3600) / 60)} min`;
}

/** FR-4.4: every Agent of the company, its health and what an Admin can do with it. */
export function AgentsPage() {
  const company = useCompany();
  const view = useCompanyQuery<Schemas["AgentsView"]>("/agents");
  const manage = can(company, "MANAGE_AGENTS");
  const register = useCompanyAction<Schemas["RegistrationTokenOut"]>(() => ({
    path: "/agents/register-token",
  }));
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Agents</h1>
        {manage && (
          <button
            type="button"
            className="rounded bg-slate-800 px-3 py-2 text-white"
            onClick={() => register.mutate()}
          >
            Register a new Agent
          </button>
        )}
      </div>
      <ErrorText error={register.error} />
      {register.data && (
        <SecretOnce
          label="Registration token"
          secret={register.data.token}
          note={
            <>
              Enter it in the Agent on the Tally computer. It works once and expires{" "}
              <TimeText value={register.data.expires_at} timeZone={company.company_timezone} />.
            </>
          }
          onClose={() => register.reset()}
        />
      )}
      <Loaded query={view} label="Loading Agents">
        {(data) => (
          <>
            <Warnings warnings={data.warnings} />
            {data.agents.length === 0 ? (
              <EmptyState>No Agent is registered yet.</EmptyState>
            ) : (
              <ul className="space-y-3">
                {data.agents.map((agent) => (
                  <AgentCard key={agent.agent_id} agent={agent} manage={manage} />
                ))}
              </ul>
            )}
          </>
        )}
      </Loaded>
    </section>
  );
}

function AgentCard({ agent, manage }: { agent: Agent; manage: boolean }) {
  const tz = useCompany().company_timezone;
  const queue = agent.queue_status as Queue | null;
  const tally = agent.last_tally_status;
  return (
    <li className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold break-all">{agent.agent_name}</h2>
        <Badge tone={STATUS_TONE[agent.status]}>{agent.status}</Badge>
      </div>
      {agent.uptime_advisory === "prominent" && (
        <p
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
        >
          Restart recommended: Tally has been running for a long time and the latest reconciliation
          failed. Restart Tally, then run reconciliation again.
        </p>
      )}
      {agent.uptime_advisory === "advisory" && (
        <p
          role="alert"
          className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          Restart recommended: Tally has been running for a long time.
        </p>
      )}
      {tally && tally !== "OK" && (
        <p
          role="alert"
          className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          {messageForCode(tally)}
          {agent.tally_status_since && (
            <>
              {" "}
              (since <TimeText value={agent.tally_status_since} timeZone={tz} />)
            </>
          )}
        </p>
      )}
      <Warnings warnings={agent.warnings} />
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-slate-600">Last contact</dt>
        <dd>
          <TimeText value={agent.last_heartbeat_at} timeZone={tz} />
          {agent.offline_since && (
            <>
              {" "}
              · offline since <TimeText value={agent.offline_since} timeZone={tz} />
            </>
          )}
        </dd>
        <dt className="text-slate-600">Versions</dt>
        <dd className="break-words">
          Agent {agent.agent_version ?? "—"} · TDL {agent.tdl_version ?? "—"} · Tally{" "}
          {agent.tally_version ?? "—"}
        </dd>
        <dt className="text-slate-600">Tally</dt>
        <dd className="break-all">
          {agent.tally_company_name ?? "—"} at {agent.tally_host ?? "—"}:{agent.tally_port ?? "—"}
          {tally === "OK" && " · running"}
        </dd>
        <dt className="text-slate-600">Tally uptime</dt>
        <dd>{agent.tally_uptime_seconds === null ? "—" : duration(agent.tally_uptime_seconds)}</dd>
        <dt className="text-slate-600">Queue</dt>
        <dd>
          {queue
            ? `${queue.records} waiting · ${queue.dead_letter_count} failed${queue.full ? " · FULL" : ""}`
            : "—"}
        </dd>
        <dt className="text-slate-600">Batch size</dt>
        <dd>{agent.extraction_batch_size ?? "default"}</dd>
      </dl>
      {manage && agent.status !== "REVOKED" && <AgentActions agent={agent} />}
    </li>
  );
}

function AgentActions({ agent }: { agent: Agent }) {
  const [open, setOpen] = useState<"settings" | "rotate" | "revoke" | null>(null);
  const base = `/agents/${agent.agent_id}`;
  const rotate = useCompanyAction<Schemas["RotatedCredential"]>(() => ({
    path: `${base}/rotate-credential`,
  }));
  const revoke = useCompanyAction(() => ({ path: `${base}/revoke` }));
  const button = "rounded border border-slate-300 px-3 py-1 text-sm";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={() => setOpen("settings")}>
          Tally settings
        </button>
        <button type="button" className={button} onClick={() => setOpen("rotate")}>
          Rotate credential
        </button>
        <button
          type="button"
          className={`${button} text-red-800`}
          onClick={() => setOpen("revoke")}
        >
          Revoke
        </button>
      </div>
      <ErrorText error={rotate.error ?? revoke.error} />
      {open === "settings" && <TallySettings agent={agent} onDone={() => setOpen(null)} />}
      {open === "rotate" && (
        <ConfirmDialog
          title={`Rotate the credential of ${agent.agent_name}`}
          confirmLabel="Rotate"
          onCancel={() => setOpen(null)}
          onConfirm={() => {
            setOpen(null);
            rotate.mutate();
          }}
        >
          The current credential stops working at once. Enter the new one in the Agent.
        </ConfirmDialog>
      )}
      {rotate.data && (
        <SecretOnce
          label="New Agent credential"
          secret={rotate.data.credential}
          onClose={() => rotate.reset()}
        />
      )}
      {open === "revoke" && (
        <ConfirmDialog
          title={`Revoke ${agent.agent_name}`}
          confirmLabel="Revoke"
          typed="REVOKE"
          onCancel={() => setOpen(null)}
          onConfirm={() => {
            setOpen(null);
            revoke.mutate();
          }}
        >
          The Agent can no longer sync. This cannot be undone; a revoked computer must be registered
          again.
        </ConfirmDialog>
      )}
    </div>
  );
}

function TallySettings({ agent, onDone }: { agent: Agent; onDone: () => void }) {
  const [host, setHost] = useState(agent.tally_host ?? "localhost");
  const [port, setPort] = useState(String(agent.tally_port ?? 9000));
  const [name, setName] = useState(agent.tally_company_name ?? "");
  const [batch, setBatch] = useState(
    agent.extraction_batch_size === null ? "" : String(agent.extraction_batch_size),
  );
  const [invalid, setInvalid] = useState<string | null>(null);
  const save = useCompanyAction<Schemas["AgentsView"], Schemas["TallySettingsUpdate"]>((body) => ({
    path: `/agents/${agent.agent_id}/tally-settings`,
    method: "PUT",
    body,
  }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const portNumber = toInt(port);
    const batchSize = batch.trim() === "" ? null : toInt(batch);
    if (portNumber === null || portNumber < 1 || portNumber > 65535) {
      return setInvalid("The port must be a whole number from 1 to 65,535.");
    }
    if (batch.trim() !== "" && (batchSize === null || batchSize < 1 || batchSize > 10000)) {
      return setInvalid("The batch size must be a whole number from 1 to 10,000.");
    }
    setInvalid(null);
    save.mutate(
      {
        tally_host: host.trim(),
        tally_port: portNumber,
        tally_company_name: name.trim() || null,
        extraction_batch_size: batchSize,
      },
      { onSuccess: onDone },
    );
  }

  const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";
  return (
    <form onSubmit={submit} className="grid gap-2 rounded bg-slate-50 p-3 sm:grid-cols-2">
      <label className="text-sm">
        Tally host
        <input className={input} required value={host} onChange={(e) => setHost(e.target.value)} />
      </label>
      <label className="text-sm">
        Tally port
        <input
          className={input}
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value)}
        />
      </label>
      <label className="text-sm">
        Company name in Tally
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="text-sm">
        Batch size (1–10,000; empty for the default)
        <input
          className={input}
          inputMode="numeric"
          value={batch}
          onChange={(e) => setBatch(e.target.value)}
        />
      </label>
      <div className="space-y-1 sm:col-span-2">
        {invalid && (
          <p role="alert" className="text-sm text-red-800">
            {invalid}
          </p>
        )}
        <ErrorText error={save.error} />
        <div className="flex gap-2">
          <button type="submit" className="rounded bg-slate-800 px-3 py-1 text-white">
            Save
          </button>
          <button type="button" className="rounded px-3 py-1" onClick={onDone}>
            Cancel
          </button>
        </div>
      </div>
    </form>
  );
}
