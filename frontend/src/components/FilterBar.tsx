import { useId, useState } from "react";
import type { Schemas } from "../api/types";
import { useCompany } from "../lib/company";
import { periodPresets, todayIn, useFilters, type FilterKey } from "../lib/filters";
import { useCompanyQuery } from "../lib/queries";

type Kind = "customer" | "product" | "cost_centre";
const PICKERS: { kind: Kind; label: string }[] = [
  { kind: "customer", label: "Customer" },
  { kind: "product", label: "Product" },
  { kind: "cost_centre", label: "Cost centre" },
];

const field = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";

/** FR-4.3's filters, kept in the URL: a period (presets or dates), and a customer, product or
 * cost centre. `pickers={false}` shows the period only (Home). */
export function FilterBar({ pickers = true }: { pickers?: boolean }) {
  const company = useCompany();
  const { filters, set } = useFilters();
  const presets = periodPresets(todayIn(company.company_timezone), company.financial_year_start);
  const chosen = presets.find((p) => p.from === filters.from && p.to === filters.to);
  const current = filters.from || filters.to ? (chosen?.label ?? "custom") : presets[0]?.label;
  return (
    <form
      aria-label="Filters"
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => e.preventDefault()}
    >
      <label className="flex flex-col text-xs">
        Period
        <select
          className={field}
          value={current}
          onChange={(e) => {
            const p = presets.find((x) => x.label === e.target.value);
            if (p) set({ from: p.from, to: p.to });
          }}
        >
          {presets.map((p) => (
            <option key={p.label} value={p.label}>
              {p.label}
            </option>
          ))}
          <option value="custom" disabled>
            Custom dates
          </option>
        </select>
      </label>
      {(["from", "to"] as const).map((key) => (
        <label key={key} className="flex flex-col text-xs">
          {key === "from" ? "From" : "To"}
          <input
            type="date"
            className={field}
            value={filters[key] ?? (key === "from" ? presets[0]?.from : presets[0]?.to) ?? ""}
            onChange={(e) => set({ [key]: e.target.value })}
          />
        </label>
      ))}
      {pickers &&
        PICKERS.map((p) => (
          <Picker
            key={p.kind}
            kind={p.kind}
            label={p.label}
            value={filters[p.kind as FilterKey]}
            onChange={(id) => set({ [p.kind]: id })}
          />
        ))}
    </form>
  );
}

/** A searchable choice from `/masters/options`. A shared link carries only the id, so the
 * chosen one is looked up by id for its name. */
function Picker({
  kind,
  label,
  value,
  onChange,
}: {
  kind: Kind;
  label: string;
  value: string | undefined;
  onChange: (id: string | undefined) => void;
}) {
  const listId = useId();
  const [text, setText] = useState("");
  const options = useCompanyQuery<Schemas["OptionOut"][]>("/masters/options", {
    query: { kind, q: text || undefined },
    enabled: !value,
  });
  const chosen = useCompanyQuery<Schemas["OptionOut"][]>("/masters/options", {
    query: { kind, id: value },
    enabled: Boolean(value),
  });
  if (value) {
    const name = chosen.data?.[0]?.name ?? "…";
    return (
      <span className="flex flex-col text-xs">
        {label}
        <span className={`${field} flex max-w-60 items-center gap-1`}>
          <span className="truncate">{name}</span>
          <button
            type="button"
            aria-label={`Clear ${label.toLowerCase()} filter`}
            className="px-1 text-slate-600"
            onClick={() => onChange(undefined)}
          >
            ×
          </button>
        </span>
      </span>
    );
  }
  return (
    <label className="flex flex-col text-xs">
      {label}
      <input
        list={listId}
        className={`${field} w-44`}
        placeholder="All"
        value={text}
        onChange={(e) => {
          const match = options.data?.find((o) => o.name === e.target.value);
          if (match) {
            onChange(match.id);
            setText("");
          } else setText(e.target.value);
        }}
      />
      <datalist id={listId}>
        {options.data?.map((o) => (
          <option key={o.id} value={o.name} />
        ))}
      </datalist>
    </label>
  );
}
