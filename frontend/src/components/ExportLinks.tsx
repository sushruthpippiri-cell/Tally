import { useState } from "react";
import { api } from "../api/client";
import { useCompany } from "../lib/company";
import { useFilters } from "../lib/filters";
import { ErrorText } from "../lib/queries";

/** EXP-1.1-1.6: the view's figures as a file. The server produces it from the same query
 * functions the page used, so what downloads is what is on screen - nothing is recomputed or
 * re-formatted here (D-051 #5). The current filters and narrowing go along as they are. */
export function ExportLinks({
  report,
  extra = {},
}: {
  report: string;
  /** The view's own parameters: `group_by`, `by`, `rank_by`, `period_days`, `class`, ... */
  extra?: Record<string, string | readonly string[] | undefined>;
}) {
  const { company_id } = useCompany();
  const { filters } = useFilters();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function download(format: "csv" | "pdf") {
    setError(null);
    setBusy(format);
    try {
      const file = await api<Blob>(`/companies/${company_id}/exports/${report}`, {
        query: { ...filters, ...extra, format },
        as: "blob",
      });
      const url = URL.createObjectURL(file);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${report}.${format}`; // the server's own name, if it sent one, wins in Chrome
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {(["csv", "pdf"] as const).map((format) => (
        <button
          key={format}
          type="button"
          className="rounded border border-slate-300 bg-white px-3 py-1 text-sm disabled:opacity-60"
          disabled={busy !== null}
          onClick={() => void download(format)}
        >
          {busy === format
            ? `Preparing ${format.toUpperCase()}…`
            : `Export ${format.toUpperCase()}`}
        </button>
      ))}
      <ErrorText error={error} />
    </div>
  );
}
