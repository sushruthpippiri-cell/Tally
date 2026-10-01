import { describe, expect, it } from "vitest";
import { describeCron } from "./cron";

describe("cron preview (P13.7)", () => {
  it.each([
    ["0 * * * *", "Every hour at :00"],
    ["15 * * * *", "Every hour at :15"],
    ["*/30 * * * *", "Every 30 minutes"],
    ["0 */4 * * *", "Every 4 hours at :00"],
    ["0 2 * * *", "Every day at 02:00"],
    ["30 9 * * 1", "Mondays at 09:30"],
    ["0 18 * * 0", "Sundays at 18:00"],
    ["0 18 * * 7", "Sundays at 18:00"],
    ["0 9 * * 1-5", "Weekdays (Monday to Friday) at 09:00"],
    ["45 23 1 * *", "On day 1 of every month at 23:45"],
  ])("%s → %s", (expression, words) => {
    expect(describeCron(expression)).toBe(words);
  });

  it.each(["0 2 * 1 *", "0 25 * * *", "61 * * * *", "0 2 * * MON", "nonsense", "0 9 1 * 1"])(
    "leaves %s as it is",
    (expression) => {
      expect(describeCron(expression)).toBeNull();
    },
  );
});
