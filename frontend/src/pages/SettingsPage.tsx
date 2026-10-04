import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api/client";
import type { Schemas } from "../api/types";
import { Badge } from "../components/ui";
import { can, useCompany } from "../lib/company";
import { toInt } from "../lib/integers";
import { ErrorText, fieldErrors, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";

type SettingsOut = Schemas["SettingsOut"];
type Group = Schemas["GroupOut"];
type Entry =
  { type: "PREDEFINED"; reserved_name: string } | { type: "COMPANY_GROUP"; tally_guid: string };
type Resolved = Entry & { display_name: string | null; is_missing: boolean };

const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";
const save = "rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-50";

function Saved({ show }: { show: boolean }) {
  return show ? (
    <p role="status" className="text-sm text-green-800">
      Saved.
    </p>
  ) : null;
}

function FieldError({ message }: { message?: string }) {
  return message ? (
    <span role="alert" className="block text-sm text-red-800">
      {message}
    </span>
  ) : null;
}

export function SettingsPage() {
  const company = useCompany();
  const tabs: [string, string, ReactNode][] = [
    ["company", "Company", <CompanyProfile key="c" />],
    ["classification", "Classification", <Classification key="cl" />],
    ["thresholds", "Thresholds", <Thresholds key="t" />],
    ["flags", "Feature flags", <Flags key="f" />],
    ...(can(company, "MANAGE_CUSTOM_FIELDS")
      ? ([["custom-fields", "Custom fields", <CustomFields key="u" />]] as [
          string,
          string,
          ReactNode,
        ][])
      : []),
  ];
  const [tab, setTab] = useState("company");
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <div role="tablist" aria-label="Settings" className="flex flex-wrap gap-1">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`rounded px-3 py-1 text-sm ${tab === id ? "bg-slate-800 text-white" : "bg-slate-100"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{tabs.find(([id]) => id === tab)?.[2]}</div>
    </section>
  );
}

function CompanyProfile() {
  const company = useCompany();
  const [name, setName] = useState(company.name);
  const [tz, setTz] = useState(company.company_timezone);
  const [fy, setFy] = useState(company.financial_year_start);
  const update = useCompanyAction<Schemas["CompanyOut"], Schemas["CompanyUpdate"]>((body) => ({
    path: "",
    method: "PUT",
    body,
  }));
  const errors = fieldErrors(update.error);
  const zones =
    typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate({ name: name.trim(), company_timezone: tz.trim(), financial_year_start: fy });
  }
  return (
    <form onSubmit={submit} className="max-w-md space-y-3">
      <label className="block text-sm">
        Company name
        <input required className={input} value={name} onChange={(e) => setName(e.target.value)} />
        <FieldError message={errors.name} />
      </label>
      <label className="block text-sm">
        Time zone (every date and time is shown in it)
        <input
          list="time-zones"
          required
          className={input}
          value={tz}
          onChange={(e) => setTz(e.target.value)}
        />
        <datalist id="time-zones">
          {zones.map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
        <FieldError message={errors.company_timezone} />
      </label>
      <label className="block text-sm">
        Financial year starts on
        <input
          type="date"
          required
          className={input}
          value={fy}
          onChange={(e) => setFy(e.target.value)}
        />
        <FieldError message={errors.financial_year_start} />
      </label>
      {Object.keys(errors).length === 0 && <ErrorText error={update.error} />}
      <Saved show={update.isSuccess} />
      <button type="submit" className={save} disabled={update.isPending}>
        Save
      </button>
    </form>
  );
}

function useSettingsSave() {
  return useCompanyAction<SettingsOut, Partial<Schemas["SettingsUpdate"]>>((body) => ({
    path: "/settings",
    method: "PUT",
    body,
  }));
}

const ALLOW_LISTS: [string, string][] = [
  ["classification.sales_groups", "Sales"],
  ["classification.purchase_groups", "Purchases"],
  ["classification.expense_groups", "Expenses"],
  ["classification.cash_bank_groups", "Cash and bank"],
  ["classification.tax_groups", "Taxes"],
];

function entryKey(e: Entry): string {
  return e.type === "PREDEFINED" ? `P:${e.reserved_name}` : `G:${e.tally_guid}`;
}

/** The identifier the API expects (D-001): reserved name for a predefined group, GUID for one of
 * the company's own top-level groups. Never the display name. */
function entryFor(group: Group): Entry | null {
  if (group.is_predefined && group.reserved_name) {
    return { type: "PREDEFINED", reserved_name: group.reserved_name };
  }
  if (!group.is_predefined && group.parent_group_id === null) {
    return { type: "COMPANY_GROUP", tally_guid: group.tally_guid };
  }
  return null;
}

function Classification() {
  const settings = useCompanyQuery<SettingsOut>("/settings");
  const groups = useCompanyQuery<Group[]>("/masters/groups");
  return (
    <Loaded query={settings} label="Loading settings">
      {(s) => (
        <Loaded query={groups} label="Loading groups">
          {(g) => <ClassificationForm settings={s} groups={g} />}
        </Loaded>
      )}
    </Loaded>
  );
}

function ClassificationForm({ settings, groups }: { settings: SettingsOut; groups: Group[] }) {
  const value = (key: string) => settings.settings[key]?.value;
  const [lists, setLists] = useState<Record<string, Resolved[]>>(() =>
    Object.fromEntries(
      ALLOW_LISTS.map(([key]) => [key, (value(key) as Resolved[] | undefined) ?? []]),
    ),
  );
  const [taxable, setTaxable] = useState(value("analytics.taxable_value_mode") === true);
  const [journals, setJournals] = useState(value("cashflow.include_journal") === true);
  const update = useSettingsSave();
  const errors = fieldErrors(update.error);
  const candidates = groups
    .filter((g) => g.status === "ACTIVE")
    .flatMap((g) => {
      const entry = entryFor(g);
      return entry ? [{ entry, name: g.name, predefined: g.is_predefined }] : [];
    });

  function toggle(key: string, entry: Entry, name: string, on: boolean) {
    setLists((all) => {
      const list = all[key] ?? [];
      const rest = list.filter((e) => entryKey(e) !== entryKey(entry));
      return {
        ...all,
        [key]: on ? [...rest, { ...entry, display_name: name, is_missing: false }] : rest,
      };
    });
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const strip = (list: Resolved[]): Entry[] =>
      list.map((e) =>
        e.type === "PREDEFINED"
          ? { type: e.type, reserved_name: e.reserved_name }
          : { type: e.type, tally_guid: e.tally_guid },
      );
    update.mutate({
      settings: {
        ...Object.fromEntries(Object.entries(lists).map(([k, list]) => [k, strip(list)])),
        "analytics.taxable_value_mode": taxable,
        "cashflow.include_journal": journals,
      },
    });
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-slate-700">
        Which groups count as sales, purchases and so on. Each list holds Tally&apos;s predefined
        groups and your own top-level groups; a ledger counts by the group it finally belongs to.
      </p>
      {ALLOW_LISTS.map(([key, label]) => {
        const chosen = lists[key] ?? [];
        const chosenKeys = new Set(chosen.map(entryKey));
        const stale = chosen.filter((e) => e.is_missing);
        return (
          <fieldset key={key} className="rounded border border-slate-200 p-3">
            <legend className="px-1 font-medium">{label}</legend>
            <FieldError message={errors[key]} />
            {stale.map((e) => (
              <label key={entryKey(e)} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked onChange={() => toggle(key, e, "", false)} />
                <span className="break-all">
                  {e.display_name ?? (e.type === "COMPANY_GROUP" ? e.tally_guid : e.reserved_name)}
                </span>
                <Badge tone="warn">No longer in Tally</Badge>
              </label>
            ))}
            <div className="grid gap-1 sm:grid-cols-2">
              {candidates.map(({ entry, name, predefined }) => (
                <label key={entryKey(entry)} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={chosenKeys.has(entryKey(entry))}
                    onChange={(e) => toggle(key, entry, name, e.target.checked)}
                  />
                  <span className="break-all">{name}</span>
                  {!predefined && <span className="text-xs text-slate-500">your group</span>}
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={taxable} onChange={(e) => setTaxable(e.target.checked)} />
        Show sales and purchases as taxable value (before GST)
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={journals} onChange={(e) => setJournals(e.target.checked)} />
        Include journal vouchers in cash flow
      </label>
      {Object.keys(errors).length === 0 && <ErrorText error={update.error} />}
      <Saved show={update.isSuccess} />
      <button type="submit" className={save} disabled={update.isPending}>
        Save classification
      </button>
    </form>
  );
}

type Kind = "int" | "decimal" | "days" | { choices: string[] };
const THRESHOLDS: [string, [string, string, Kind][]][] = [
  ["Aging", [["aging.bucket_boundaries", "Bucket boundaries in days, e.g. 30, 60, 90", "days"]]],
  [
    "Payment behaviour",
    [
      ["payment.window_days", "Look back this many days", "int"],
      ["payment.min_settlements", "Minimum settled bills to show a figure", "int"],
    ],
  ],
  [
    "Stock",
    [
      [
        "stock.measurement_period_days",
        "Measurement period (days)",
        { choices: ["30", "60", "90", "180"] },
      ],
      ["stock.fast_percentile", "Fast-moving above this percentile", "int"],
      ["stock.slow_threshold_days", "Slow-moving after this many days without a sale", "int"],
      ["stock.dead_stock_days", "Dead stock after this many days without a sale", "int"],
      ["stock.snapshot_stale_days", "Warn when the stock snapshot is older than (days)", "int"],
    ],
  ],
  [
    "Reconciliation tolerances",
    [
      ["reconciliation.money_absolute_tolerance", "Money: absolute (₹)", "decimal"],
      ["reconciliation.money_percentage_tolerance", "Money: percentage", "decimal"],
      ["reconciliation.quantity_absolute_tolerance", "Quantity: absolute", "decimal"],
      ["reconciliation.quantity_percentage_tolerance", "Quantity: percentage", "decimal"],
    ],
  ],
  [
    "Reports",
    [
      ["analytics.top_n_default", "Top-N lists show this many", "int"],
      ["analytics.quarter_mode", "Quarters follow", { choices: ["financial", "calendar"] }],
    ],
  ],
];

function shown(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return value === null || value === undefined ? "" : String(value);
}

function Thresholds() {
  const settings = useCompanyQuery<SettingsOut>("/settings");
  return (
    <Loaded query={settings} label="Loading settings">
      {(s) => <ThresholdsForm settings={s} />}
    </Loaded>
  );
}

function ThresholdsForm({ settings }: { settings: SettingsOut }) {
  const fields = THRESHOLDS.flatMap(([, list]) => list);
  const [text, setText] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(([key]) => [key, shown(settings.settings[key]?.value)])),
  );
  const [invalid, setInvalid] = useState<Record<string, string>>({});
  const update = useSettingsSave();
  const errors = { ...fieldErrors(update.error), ...invalid };

  function submit(event: FormEvent) {
    event.preventDefault();
    const out: Record<string, unknown> = {};
    const bad: Record<string, string> = {};
    for (const [key, , kind] of fields) {
      const raw = (text[key] ?? "").trim();
      if (raw === shown(settings.settings[key]?.value)) continue; // unchanged
      if (kind === "int" || (typeof kind === "object" && key === "stock.measurement_period_days")) {
        const n = toInt(raw);
        if (n === null) bad[key] = "must be a whole number";
        else out[key] = n;
      } else if (kind === "days") {
        const days = raw.split(",").map((d) => toInt(d));
        if (days.some((d) => d === null)) bad[key] = "must be whole numbers separated by commas";
        else out[key] = days;
      } else {
        out[key] = raw; // decimals stay strings (D-051 #5); choices are strings
      }
    }
    setInvalid(bad);
    if (Object.keys(bad).length === 0) update.mutate({ settings: out });
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      {THRESHOLDS.map(([title, list]) => (
        <fieldset
          key={title}
          className="grid gap-2 rounded border border-slate-200 p-3 sm:grid-cols-2"
        >
          <legend className="px-1 font-medium">{title}</legend>
          {list.map(([key, label, kind]) => (
            <label key={key} className="text-sm">
              {label}
              {settings.settings[key]?.is_default && (
                <span className="ml-1 text-xs text-slate-500">(default)</span>
              )}
              {typeof kind === "object" ? (
                <select
                  className={input}
                  value={text[key]}
                  onChange={(e) => setText({ ...text, [key]: e.target.value })}
                >
                  {kind.choices.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className={input}
                  inputMode={kind === "decimal" ? "decimal" : "numeric"}
                  value={text[key]}
                  onChange={(e) => setText({ ...text, [key]: e.target.value })}
                />
              )}
              <FieldError message={errors[key]} />
            </label>
          ))}
        </fieldset>
      ))}
      {Object.keys(errors).length === 0 && <ErrorText error={update.error} />}
      <Saved show={update.isSuccess} />
      <button type="submit" className={save} disabled={update.isPending}>
        Save thresholds
      </button>
    </form>
  );
}

const FLAG_LABELS: Record<string, string> = {
  FEATURE_ANOMALY_DETECTION: "Anomaly detection (explanations may use Claude; figures never do)",
};

function Flags() {
  const settings = useCompanyQuery<SettingsOut>("/settings");
  const update = useSettingsSave();
  return (
    <Loaded query={settings} label="Loading feature flags">
      {(s) => (
        <div className="space-y-2">
          {Object.entries(s.feature_flags).map(([name, flag]) => (
            <label key={name} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={flag.enabled}
                disabled={update.isPending}
                onChange={(e) => update.mutate({ feature_flags: { [name]: e.target.checked } })}
              />
              {FLAG_LABELS[name] ?? name}
              {flag.is_default && <span className="text-xs text-slate-500">(default)</span>}
            </label>
          ))}
          <ErrorText error={update.error} />
        </div>
      )}
    </Loaded>
  );
}

type Mapping = Schemas["UdfMapping"];
const COLLECTIONS: Mapping["collection_type"][] = [
  "LEDGER",
  "STOCK_ITEM",
  "VOUCHER",
  "VOUCHER_TYPE",
  "GROUP",
  "COST_CENTRE",
];
const UDF_TYPES: Mapping["data_type"][] = ["TEXT", "NUMBER", "DATE", "LOGICAL"];

function CustomFields() {
  const mappings = useCompanyQuery<Mapping[]>("/settings/custom-fields");
  return (
    <Loaded query={mappings} label="Loading custom fields">
      {(list) => <CustomFieldsForm initial={list} />}
    </Loaded>
  );
}

function CustomFieldsForm({ initial }: { initial: Mapping[] }) {
  const { company_id } = useCompany();
  const [rows, setRows] = useState<Mapping[]>(initial);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const update = useCompanyAction<Mapping[], Mapping[]>((mappings) => ({
    path: "/settings/custom-fields",
    method: "PUT",
    body: { mappings },
  }));
  const edit = (i: number, change: Partial<Mapping>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...change } : r)));

  async function download() {
    setDownloadError(null);
    try {
      const text = await api<string>(`/companies/${company_id}/settings/custom-fields/tdl`, {
        as: "text",
      });
      const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "TallyAnalytics_UDF.tdl";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError(e);
    }
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        update.mutate(rows);
      }}
      className="space-y-3"
    >
      <p className="text-sm text-slate-700">
        Tally fields to bring across with each record. After changing them, download the TDL and
        load it in TallyPrime next to the Tally Analytics TDL.
      </p>
      {rows.map((row, i) => (
        <div key={i} className="grid gap-2 rounded border border-slate-200 p-2 sm:grid-cols-5">
          <label className="text-sm">
            Record
            <select
              className={input}
              value={row.collection_type}
              onChange={(e) =>
                edit(i, { collection_type: e.target.value as Mapping["collection_type"] })
              }
            >
              {COLLECTIONS.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Tally field
            <input
              required
              className={input}
              value={row.tally_field}
              onChange={(e) => edit(i, { tally_field: e.target.value })}
            />
          </label>
          <label className="text-sm">
            Name here
            <input
              required
              className={input}
              value={row.field_key}
              onChange={(e) => edit(i, { field_key: e.target.value })}
            />
          </label>
          <label className="text-sm">
            Type
            <select
              className={input}
              value={row.data_type}
              onChange={(e) => edit(i, { data_type: e.target.value as Mapping["data_type"] })}
            >
              {UDF_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="self-end rounded px-2 py-1 text-sm text-red-800"
            onClick={() => setRows(rows.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded border border-slate-300 px-3 py-2"
          onClick={() =>
            setRows([
              ...rows,
              { collection_type: "LEDGER", tally_field: "", field_key: "", data_type: "TEXT" },
            ])
          }
        >
          Add a field
        </button>
        <button type="submit" className={save} disabled={update.isPending}>
          Save custom fields
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-3 py-2"
          onClick={() => void download()}
        >
          Download UDF TDL
        </button>
      </div>
      <ErrorText error={update.error ?? downloadError} />
      <Saved show={update.isSuccess} />
    </form>
  );
}
