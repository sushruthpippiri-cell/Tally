import { toInt } from "./integers";

const DAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"];

function clock(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function inRange(text: string, low: number, high: number): number | null {
  const n = toInt(text);
  return n !== null && n >= low && n <= high ? n : null;
}

/** Plain words for the common five-field cron patterns; null for anything else (the expression
 * is then shown as it is). The backend evaluates it in the company's time zone (TZ-1.1). */
export function describeCron(expression: string): string | null {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const [min = "", hour = "", dom = "", month = "", dow = ""] = fields;
  if (month !== "*") return null;
  const step = /^\*\/(\d+)$/;
  const everyMinutes = step.exec(min);
  if (everyMinutes && hour === "*" && dom === "*" && dow === "*") {
    const n = inRange(everyMinutes[1] ?? "", 1, 59);
    return n === null ? null : n === 1 ? "Every minute" : `Every ${n} minutes`;
  }
  const minute = inRange(min, 0, 59);
  if (minute === null) return null;
  const everyHours = step.exec(hour);
  if (everyHours && dom === "*" && dow === "*") {
    const n = inRange(everyHours[1] ?? "", 1, 23);
    return n === null ? null : `Every ${n} hours at :${String(minute).padStart(2, "0")}`;
  }
  if (hour === "*" && dom === "*" && dow === "*") {
    return `Every hour at :${String(minute).padStart(2, "0")}`;
  }
  const h = inRange(hour, 0, 23);
  if (h === null) return null;
  const at = clock(h, minute);
  if (dom === "*" && dow === "*") return `Every day at ${at}`;
  if (dom === "*" && dow === "1-5") return `Weekdays (Monday to Friday) at ${at}`;
  const day = dom === "*" ? inRange(dow, 0, 7) : null;
  if (day !== null) return `${DAYS[day % 7]} at ${at}`;
  const date = dow === "*" ? inRange(dom, 1, 31) : null;
  if (date !== null) return `On day ${date} of every month at ${at}`;
  return null;
}
