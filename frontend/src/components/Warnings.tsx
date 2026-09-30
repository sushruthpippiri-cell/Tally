/** Everything that qualifies a figure, shown next to it: never collapsed, never dismissible
 * (D-051 #7). Pages pass whatever the API sent; an empty list renders nothing. */
export interface WarningsProps {
  unverifiedGates?: readonly string[] | null;
  warnings?: readonly string[] | null;
  notes?: readonly string[] | null;
  limitations?: readonly string[] | null;
}

export function Warnings({ unverifiedGates, warnings, notes, limitations }: WarningsProps) {
  const gates = unverifiedGates ?? [];
  const items: { key: string; text: string; tone: "warn" | "info" }[] = [
    ...(warnings ?? []).map((text, i) => ({ key: `w${i}`, text, tone: "warn" as const })),
    ...(limitations ?? []).map((text, i) => ({ key: `l${i}`, text, tone: "warn" as const })),
    ...(gates.length > 0
      ? [
          {
            key: "gates",
            text: `Awaiting Tally validation (${gates.join(", ")}): these figures rely on a reading of Tally's data that has not yet been checked against a live Tally.`,
            tone: "info" as const,
          },
        ]
      : []),
    ...(notes ?? []).map((text, i) => ({ key: `n${i}`, text, tone: "info" as const })),
  ];
  if (items.length === 0) return null;
  return (
    <ul aria-label="Warnings and notes" className="my-2 space-y-1 text-sm">
      {items.map((item) => (
        <li
          key={item.key}
          role={item.tone === "warn" ? "alert" : "note"}
          className={
            item.tone === "warn"
              ? "rounded border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900"
              : "rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sky-900"
          }
        >
          {item.text}
        </li>
      ))}
    </ul>
  );
}
