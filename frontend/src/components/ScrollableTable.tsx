import type { ReactNode } from "react";

/** Every table goes in here: wide content scrolls inside this box, never the page (NFR-UI-1). */
export function ScrollableTable({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="max-w-full overflow-x-auto rounded border border-slate-200" tabIndex={0}>
      <table className="min-w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}
