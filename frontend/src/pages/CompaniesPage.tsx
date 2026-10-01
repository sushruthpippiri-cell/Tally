import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { EmptyState, Loading } from "../components/ui";
import type { Company } from "../lib/company";
import { messageFor } from "../lib/errorMessages";
import { SignOut } from "./SignOut";

/** One company at a time (P13.4): with one company, go straight in. */
export function CompaniesPage() {
  const companies = useQuery({
    queryKey: ["companies"],
    queryFn: () => api<Company[]>("/companies"),
  });
  if (companies.isPending) return <Loading label="Loading companies" />;
  if (companies.isError) {
    const error = companies.error;
    return (
      <p role="alert" className="p-4 text-red-800">
        {error instanceof ApiError ? messageFor(error) : "Companies could not be loaded."}
      </p>
    );
  }
  const [only] = companies.data;
  if (companies.data.length === 1 && only) {
    return <Navigate to={`/c/${only.company_id}/home`} replace />;
  }
  return (
    <main className="mx-auto max-w-xl space-y-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Companies</h1>
        <SignOut />
      </div>
      {companies.data.length === 0 ? (
        <EmptyState>
          You have no company yet. Ask its Owner to add you, or create one through the API.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
          {companies.data.map((c) => (
            <li key={c.company_id}>
              <Link to={`/c/${c.company_id}/home`} className="block px-4 py-3 hover:bg-slate-50">
                <span className="block font-medium">{c.name}</span>
                <span className="block text-sm text-slate-600">
                  {c.my_roles.join(", ")} · {c.company_timezone}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
