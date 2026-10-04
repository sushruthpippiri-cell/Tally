import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, ApiError, type RequestOptions } from "../api/client";
import { Loading } from "../components/ui";
import { useCompany } from "./company";
import { messageFor } from "./errorMessages";

/** A GET under the current company. The query key starts with the company id, so an action
 * refreshes everything shown for that company. */
export function useCompanyQuery<T>(
  path: string,
  options: {
    query?: RequestOptions["query"];
    /** Milliseconds, or decided from the latest answer (e.g. stop once a command is done). */
    poll?: (data: T | undefined) => number | false;
    enabled?: boolean;
  } = {},
): UseQueryResult<T> {
  const { company_id } = useCompany();
  const { poll } = options;
  return useQuery({
    queryKey: [company_id, path, options.query ?? {}],
    queryFn: () => api<T>(`/companies/${company_id}${path}`, { query: options.query }),
    refetchInterval: poll ? (query) => poll(query.state.data) : false,
    enabled: options.enabled ?? true,
  });
}

/** A change under the current company; on success everything shown for it is fetched again. */
export function useCompanyAction<T, V = void>(
  request: (vars: V) => { path: string; method?: RequestOptions["method"]; body?: unknown },
) {
  const { company_id } = useCompany();
  const queries = useQueryClient();
  return useMutation<T, unknown, V>({
    mutationFn: (vars) => {
      const { path, method = "POST", body } = request(vars);
      return api<T>(`/companies/${company_id}${path}`, { method, body });
    },
    onSuccess: () => queries.invalidateQueries({ queryKey: [company_id] }),
  });
}

/** A 422's per-field messages, by setting key or request field (both shapes the API sends). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "VALIDATION_ERROR") return {};
  const list = (error.details as { errors?: unknown } | null)?.errors;
  if (!Array.isArray(list)) return {};
  const out: Record<string, string> = {};
  for (const item of list as { key?: string; message?: string; loc?: unknown[]; msg?: string }[]) {
    const key = item.key ?? String(item.loc?.at(-1) ?? "");
    out[key] = item.message ?? item.msg ?? "is not valid";
  }
  return out;
}

export function errorText(error: unknown): string {
  return error instanceof ApiError ? messageFor(error) : "Something went wrong. Please try again.";
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-red-800">
      {errorText(error)}
    </p>
  );
}

/** Loading, then the error, then the page. */
export function Loaded<T>({
  query,
  label,
  children,
}: {
  query: UseQueryResult<T>;
  label: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Loading label={label} />;
  if (query.isError) return <ErrorText error={query.error} />;
  return <>{children(query.data)}</>;
}
