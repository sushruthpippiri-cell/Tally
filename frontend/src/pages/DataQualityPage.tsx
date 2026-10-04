import { useState } from "react";
import type { Schemas } from "../api/types";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge, DateText, EmptyState, TimeText } from "../components/ui";
import { useCompany } from "../lib/company";
import { Loaded, useCompanyQuery } from "../lib/queries";

type Check = Schemas["CheckSummary"];
const PAGE = 50;
const cell = "px-3 py-2 text-left align-top";
export const SEVERITY_TONE = { ERROR: "bad", WARNING: "warn", INFO: "neutral" } as const;

/** FR-4.5: every data-quality check, its count (the backend's, never counted here) and how to
 * fix it. "Sync held back by failing records" is one of them (D-039 #7). */
export function DataQualityPage() {
  const checks = useCompanyQuery<Check[]>("/data-quality");
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Data Quality</h1>
      <Loaded query={checks} label="Loading checks">
        {(list) => (
          <ul className="space-y-3">
            {list.map((c) => (
              <li
                key={c.check_id}
                className="space-y-2 rounded border border-slate-200 bg-white p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{c.title}</h2>
                  <Badge tone={c.count === 0 ? "ok" : SEVERITY_TONE[c.severity]}>
                    {c.count === 0 ? "None" : `${c.count} · ${c.severity}`}
                  </Badge>
                </div>
                <p className="text-sm text-slate-700">{c.how_to_fix}</p>
                {c.count > 0 && (
                  <button
                    type="button"
                    className="text-sm underline"
                    aria-expanded={open === c.check_id}
                    onClick={() => setOpen(open === c.check_id ? null : c.check_id)}
                  >
                    {open === c.check_id ? "Hide" : "Show"} the {c.count} item
                    {c.count === 1 ? "" : "s"}
                  </button>
                )}
                {open === c.check_id && <CheckItems check={c} />}
              </li>
            ))}
          </ul>
        )}
      </Loaded>
    </section>
  );
}

function Value({ name, value }: { name: string; value: unknown }) {
  const tz = useCompany().company_timezone;
  if (value === null || value === undefined) return <>—</>;
  if (typeof value === "string" && name.endsWith("_at"))
    return <TimeText value={value} timeZone={tz} />;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return <DateText value={value} />;
  if (typeof value === "object") return <>{JSON.stringify(value)}</>;
  return <span className="break-all">{String(value)}</span>;
}

function CheckItems({ check }: { check: Check }) {
  const [offset, setOffset] = useState(0);
  const items = useCompanyQuery<Schemas["CheckItems"]>(`/data-quality/${check.check_id}`, {
    query: { limit: PAGE, offset },
  });
  return (
    <Loaded query={items} label="Loading items">
      {(page) => {
        const columns = [...new Set(page.items.flatMap((item) => Object.keys(item)))];
        if (page.items.length === 0) return <EmptyState>No items.</EmptyState>;
        return (
          <div className="space-y-2">
            <ScrollableTable caption={`${check.title}: items`}>
              <thead className="bg-slate-50">
                <tr>
                  {columns.map((c) => (
                    <th key={c} className={cell}>
                      {c.replaceAll("_", " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.items.map((item, i) => (
                  <tr key={i} className="border-t border-slate-200">
                    {columns.map((c) => (
                      <td key={c} className={cell}>
                        <Value name={c} value={(item as Record<string, unknown>)[c]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
            <div className="flex items-center gap-3 text-sm">
              <span>
                {page.offset + 1}–{page.offset + page.items.length} of {page.count}
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
                disabled={page.offset + page.items.length >= page.count}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          </div>
        );
      }}
    </Loaded>
  );
}
