import { useState, type ReactNode } from "react";
import { formatDate, formatTimestamp } from "../lib/format";

type Tone = "ok" | "warn" | "bad" | "neutral";
const TONES: Record<Tone, string> = {
  ok: "bg-emerald-100 text-emerald-900",
  warn: "bg-amber-100 text-amber-900",
  bad: "bg-red-100 text-red-900",
  neutral: "bg-slate-100 text-slate-800",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

/** A DATE, as it is in the books (never shifted). */
export function DateText({ value }: { value: string | null | undefined }) {
  return <span className="whitespace-nowrap">{value ? formatDate(value) : "—"}</span>;
}

/** A timestamp in the company's time zone, never the browser's (TZ-1.1). */
export function TimeText({
  value,
  timeZone,
}: {
  value: string | null | undefined;
  timeZone: string;
}) {
  return (
    <span className="whitespace-nowrap">{value ? formatTimestamp(value, timeZone) : "—"}</span>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded border border-dashed border-slate-300 p-4 text-slate-600">{children}</p>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-label={label} className="animate-pulse space-y-2 py-2">
      <div className="h-4 w-2/3 rounded bg-slate-200" />
      <div className="h-4 w-1/2 rounded bg-slate-200" />
    </div>
  );
}

/** A confirmation step before anything that cannot be undone. With `typed`, the user must type
 * that word first (e.g. revoking an Agent). */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  typed,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  typed?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const ready = typed === undefined || text === typed;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    >
      <div className="w-full max-w-md rounded bg-white p-4 shadow-lg">
        <h2 className="mb-2 text-lg font-semibold">{title}</h2>
        <div className="mb-3 text-sm">{children}</div>
        {typed !== undefined && (
          <label className="mb-3 block text-sm">
            Type <strong>{typed}</strong> to confirm
            <input
              className="mt-1 block w-full rounded border border-slate-300 px-2 py-1"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="rounded px-3 py-2" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            disabled={!ready}
            className="rounded bg-red-700 px-3 py-2 text-white disabled:opacity-50"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** A secret the server shows once (a registration token, a rotated credential). */
export function SecretOnce({
  label,
  secret,
  note,
  onClose,
}: {
  label: string;
  secret: string;
  note?: ReactNode;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={label}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    >
      <div className="w-full max-w-md rounded bg-white p-4 shadow-lg">
        <h2 className="mb-2 text-lg font-semibold">{label}</h2>
        <p className="mb-2 text-sm text-amber-900">
          This is shown only once. Copy it now; it cannot be shown again.
        </p>
        <code className="mb-3 block break-all rounded bg-slate-100 p-2 text-sm">{secret}</code>
        {note && <p className="mb-3 text-sm">{note}</p>}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="rounded border border-slate-300 px-3 py-2"
            onClick={() => {
              void navigator.clipboard.writeText(secret).then(() => setCopied(true));
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            className="rounded bg-slate-800 px-3 py-2 text-white"
            onClick={onClose}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
