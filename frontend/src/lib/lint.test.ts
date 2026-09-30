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

  it("allow whole-number conversion only in lib/integers.ts", async () => {
    const eslint = new ESLint();
    const [result] = await eslint.lintText('export const n = Number("12");', {
      filePath: "src/lib/integers.ts",
    });
    expect(result?.messages).toEqual([]);
  });
});
