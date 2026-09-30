import type { ApiError } from "../api/client";

/** One plain message per error code (P13.5 fills the catalogue). */
export function messageFor(error: ApiError): string {
  return error.message;
}
