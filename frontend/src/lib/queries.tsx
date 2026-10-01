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
  options: { query?: RequestOptions["query"]; refetchInterval?: number | false } = {},
): UseQueryResult<T> {
  const { company_id } = useCompany();
  return useQuery({
    queryKey: [company_id, path, options.query ?? {}],
    queryFn: () => api<T>(`/companies/${company_id}${path}`, { query: options.query }),
    refetchInterval: options.refetchInterval,
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
