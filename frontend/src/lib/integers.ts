/** Whole numbers that are not money (a page number, a batch size). Money never comes here: it
 * stays a decimal string (D-051 #5). The one file exempt from the no-conversion lint rule. */
export function toInt(text: string): number | null {
  if (!/^-?\d+$/.test(text.trim())) return null;
  const value = Number(text);
  return Number.isSafeInteger(value) ? value : null;
}
