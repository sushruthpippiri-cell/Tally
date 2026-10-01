import { getAccessToken, requirePasswordChange } from "../lib/session";
import type { ErrorCode } from "./types";

/** Every error the API returns has this body: `{code, message, details}` (rule 14). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode | "NETWORK_ERROR",
    message: string,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const API_BASE = "/api"; // same origin; the proxy strips it (D-051 #4)

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Query;
  headers?: Record<string, string>;
}

/** Tries once more after a 401, when a refresher is installed (lib/auth.ts, P13.3). */
let refresher: (() => Promise<boolean>) | null = null;
export function setRefresher(fn: (() => Promise<boolean>) | null): void {
  refresher = fn;
}

function url(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) params.set(key, String(value));
  }
  const search = params.toString();
  return `${API_BASE}${path}${search ? `?${search}` : ""}`;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  try {
    return await fetch(url(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "The server could not be reached.");
  }
}

export async function toError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as {
      code?: ErrorCode;
      message?: string;
      details?: unknown;
    };
    return new ApiError(
      response.status,
      body.code ?? "VALIDATION_ERROR",
      body.message ?? response.statusText,
      body.details ?? null,
    );
  } catch {
    return new ApiError(response.status, "NETWORK_ERROR", response.statusText);
  }
}

/** Typed by the caller from the generated schema: `api<Schemas["AgingOut"]>(...)`. Money in the
 * result stays a decimal string (D-051 #5). */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);
  if (response.status === 401 && refresher && (await refresher())) {
    response = await send(path, options);
  }
  if (!response.ok) {
    const error = await toError(response);
    if (error.code === "PASSWORD_CHANGE_REQUIRED") requirePasswordChange();
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
