import { expect, type Page } from "@playwright/test";

/** Collects Content Security Policy violations; a test asserts there are none (D-051 #4). */
export async function watchCsp(page: Page): Promise<string[]> {
  const violations: string[] = [];
  await page.exposeFunction("__cspViolation", (text: string) => violations.push(text));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __cspViolation: (t: string) => void }).__cspViolation(
        `${e.violatedDirective} ${e.blockedURI}`,
      );
    });
  });
  page.on("console", (message) => {
    if (message.type() === "error" && message.text().includes("Content Security Policy")) {
      violations.push(message.text());
    }
  });
  return violations;
}

/** NFR-UI-1: no page-level horizontal scrolling. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const [scrollWidth, innerWidth] = await page.evaluate(() => [
    document.scrollingElement?.scrollWidth ?? 0,
    window.innerWidth,
  ]);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth ?? 0);
}
