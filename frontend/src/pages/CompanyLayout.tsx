import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Outlet, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { CHANGE_PASSWORD } from "../components/RequireAuth";
import { Shell, type NavItem } from "../components/Shell";
import { Loading } from "../components/ui";
import { can, CompanyProvider, useCompany, type Company } from "../lib/company";
import { messageFor } from "../lib/errorMessages";
import { ForbiddenPage } from "./ForbiddenPage";
import { SignOut } from "./SignOut";

/** FR-4.2's operational sections (the analytics sections arrive in P14), each with the
 * permission its API needs (SRS 14.1). */
export const SECTIONS: readonly (NavItem & { permission: string })[] = [
  { to: "home", label: "Home", permission: "VIEW_FINANCIALS" },
  { to: "sync", label: "Sync", permission: "RUN_SYNC" },
  { to: "agents", label: "Agents", permission: "VIEW_FINANCIALS" },
  { to: "reconciliation", label: "Reconciliation", permission: "VIEW_RECON_AND_DQ" },
  { to: "data-quality", label: "Data Quality", permission: "VIEW_RECON_AND_DQ" },
  { to: "settings", label: "Settings", permission: "MANAGE_SETTINGS" },
  { to: "users", label: "Users", permission: "MANAGE_USERS" },
];

export function CompanyLayout() {
  const { companyId = "" } = useParams();
  const company = useQuery({
    queryKey: [companyId, "/"], // under the company's key, so its actions refresh it too
    queryFn: () => api<Company>(`/companies/${companyId}`),
  });
  if (company.isPending) return <Loading label="Loading the company" />;
  if (company.isError) {
    const error = company.error;
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
      return <ForbiddenPage />;
    }
    return (
      <p role="alert" className="p-4 text-red-800">
        {error instanceof ApiError ? messageFor(error) : "The company could not be loaded."}
      </p>
    );
  }
  const nav = SECTIONS.filter((s) => can(company.data, s.permission)).map((s) => ({
    to: `/c/${companyId}/${s.to}`,
    label: s.label,
  }));
  return (
    <CompanyProvider company={company.data}>
      <Shell
        title={company.data.name}
        nav={nav}
        actions={
          <>
            <Link to="/companies" className="text-sm underline">
              Switch company
            </Link>
            <Link to={CHANGE_PASSWORD} className="text-sm underline">
              Change password
            </Link>
            <SignOut />
          </>
        }
      >
        <Outlet />
      </Shell>
    </CompanyProvider>
  );
}

/** A page the user's roles do not allow shows Forbidden, as the API would answer 403. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const company = useCompany();
  return can(company, permission) ? <>{children}</> : <ForbiddenPage />;
}
