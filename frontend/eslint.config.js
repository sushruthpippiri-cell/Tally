import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// D-051 #5: money is a decimal string end to end and is never turned into a JavaScript number.
// Every total shown comes from the backend. Whole numbers that are not money (a page number, a
// batch size) go through src/lib/integers.ts, the one file exempt from this rule.
export const NO_NUMBER_CONVERSION = [
  {
    selector: "CallExpression[callee.name=/^(Number|parseFloat|parseInt)$/]",
    message:
      "No numeric conversion: money stays a string (D-051 #5); integers use lib/integers.ts.",
  },
  {
    selector:
      "CallExpression[callee.object.name='Number'][callee.property.name=/^(parseFloat|parseInt)$/]",
    message:
      "No numeric conversion: money stays a string (D-051 #5); integers use lib/integers.ts.",
  },
  {
    selector: "UnaryExpression[operator='+']",
    message: "No unary +: money stays a string (D-051 #5).",
  },
];

// D-051 #1: no token (or anything else) in browser storage.
export const NO_BROWSER_STORAGE = ["localStorage", "sessionStorage"].map((name) => ({
  name,
  message: "Nothing is kept in browser storage (D-051 #1).",
}));

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/api/schema.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": ["error", ...NO_NUMBER_CONVERSION],
      "no-restricted-globals": ["error", ...NO_BROWSER_STORAGE],
      "no-restricted-properties": [
        "error",
        ...["localStorage", "sessionStorage"].map((property) => ({
          object: "window",
          property,
          message: "Nothing is kept in browser storage (D-051 #1).",
        })),
      ],
    },
  },
  { files: ["src/lib/integers.ts"], rules: { "no-restricted-syntax": "off" } },
  // Tests read browser storage only to prove it stays empty.
  {
    files: ["**/*.test.{ts,tsx}", "e2e/**"],
    rules: { "no-restricted-globals": "off", "no-restricted-properties": "off" },
  },
);
