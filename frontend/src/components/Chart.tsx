import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toChartNumber } from "../lib/chartNumber";
import { formatMoney } from "../lib/format";

/** One bar: the backend's own label and amount (a decimal string). */
export interface ChartPoint {
  key: string;
  label: string;
  amount: string;
}

interface Drawn extends ChartPoint {
  size: number; // the bar's length only; never shown
}

/** The only file that imports Recharts (D-053 #5). Bars are sized by `toChartNumber`; every
 * text in the chart is the backend's: the category axis shows its labels, the tooltip its
 * amount through `formatMoney`, and there is no value axis, so no number Recharts computes is
 * ever shown. A tap (or click) opens the tooltip with the exact figure and a way into its
 * vouchers (NFR-UI-2); the table that follows every chart lists the same figures, so nothing
 * is hover-only and colour carries no meaning. */
export function Chart({
  title,
  points,
  onSelect,
}: {
  title: string;
  points: ChartPoint[];
  onSelect?: (key: string) => void;
}) {
  const data: Drawn[] = points.map((p) => ({ ...p, size: toChartNumber(p.amount) }));
  return (
    <figure className="space-y-1">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      <ResponsiveContainer width="100%" height={220} initialDimension={{ width: 640, height: 220 }}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis dataKey="label" interval="preserveStartEnd" tickLine={false} fontSize={12} />
          <YAxis hide />
          <Tooltip
            trigger="click"
            cursor={{ fillOpacity: 0.1 }}
            wrapperStyle={{ pointerEvents: "auto" }}
            content={({ active, payload }) => {
              const point = payload?.[0]?.payload as Drawn | undefined;
              return active && point ? <ChartTip point={point} onSelect={onSelect} /> : null;
            }}
          />
          <Bar dataKey="size" fill="#334155" cursor="pointer" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}

/** The tooltip: the label and amount exactly as the backend sent them. */
export function ChartTip({
  point,
  onSelect,
}: {
  point: ChartPoint;
  onSelect?: (key: string) => void;
}) {
  return (
    <div className="space-y-1 rounded border border-slate-300 bg-white p-2 text-sm shadow">
      <p className="font-medium">{point.label}</p>
      <p className="tabular-nums">{formatMoney(point.amount)}</p>
      {onSelect && (
        <button type="button" className="underline" onClick={() => onSelect(point.key)}>
          See vouchers
        </button>
      )}
    </div>
  );
}
