// @vitest-environment node
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

/** The lint rules that keep money a string and browser storage empty (D-051 #1, #5) fire. */
describe("lint guards", () => {
  it("reject numeric conversion, unary + and browser storage in app code", async () => {
    const eslint = new ESLint();
    const [result] = await eslint.lintText(
      [
        'export const a = parseFloat("1.5");',
        'export const b = Number("2");',
        'export const c = Number.parseInt("3", 10);',
        'export const d = +"4";',
        'localStorage.setItem("token", "x");',
        'window.sessionStorage.setItem("token", "x");',
      ].join("\n"),
      { filePath: "src/sample.ts" },
    );
    const rules = result?.messages.map((m) => m.ruleId);
    expect(rules).toEqual([
      "no-restricted-syntax",
      "no-restricted-syntax",
      "no-restricted-syntax",
      "no-restricted-syntax",
      "no-restricted-globals",
      "no-restricted-properties",
    ]);
  });

  it("allow number conversion only in lib/integers.ts and lib/chartNumber.ts", async () => {
    const eslint = new ESLint();
    const lint = async (filePath: string) =>
      (await eslint.lintText('export const n = Number("12");', { filePath }))[0]?.messages.map(
        (m) => m.ruleId,
      );
    expect(await lint("src/lib/integers.ts")).toEqual([]);
    expect(await lint("src/lib/chartNumber.ts")).toEqual([]);
    // nowhere else: not the chart component, not the money formatter, not a look-alike name
    for (const other of [
      "src/components/Chart.tsx",
      "src/lib/format.ts",
      "src/pages/SalesPage.tsx",
      "src/lib/chartNumbers.ts",
    ]) {
      expect(await lint(other)).toEqual(["no-restricted-syntax"]);
    }
  });

  it("allow Recharts only in components/Chart.tsx (D-053 #5)", async () => {
    const eslint = new ESLint();
    const source = 'import { BarChart } from "recharts";\nexport const c = BarChart;';
    const lint = async (filePath: string) =>
      (await eslint.lintText(source, { filePath }))[0]?.messages.map((m) => m.ruleId);
    expect(await lint("src/components/Chart.tsx")).toEqual([]);
    expect(await lint("src/pages/HomePage.tsx")).toEqual(["no-restricted-imports"]);
    expect(await lint("src/components/Money.tsx")).toEqual(["no-restricted-imports"]);
  });
});
