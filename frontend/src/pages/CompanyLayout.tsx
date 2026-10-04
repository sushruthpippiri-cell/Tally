import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Schemas } from "../api/types";
import { CHANGE_PASSWORD } from "../components/RequireAuth";
import { Shell, type NavItem } from "../components/Shell";
import { Loading } from "../components/ui";
import { can, CompanyProvider, useCompany, type Company } from "../lib/company";
import { readFilters, withFilters } from "../lib/filters";
import { messageFor } from "../lib/errorMessages";
import { ForbiddenPage } from "./ForbiddenPage";
import { SignOut } from "./SignOut";

/** FR-4.2's sections, each with the permission its API needs (SRS 14.1). Payment Behaviour
 * is listed only once its gate has passed (FR-PAY-6); Anomalies arrives in P15. */
export const SECTIONS: readonly (NavItem & { permission: string })[] = [
  { to: "home", label: "Home", permission: "VIEW_FINANCIALS" },
  { to: "sales", label: "Sales", permission: "VIEW_FINANCIALS" },
  { to: "purchases", label: "Purchases", permission: "VIEW_FINANCIALS" },
  { to: "cash-flow", label: "Cash Flow", permission: "VIEW_FINANCIALS" },
  { to: "balances", label: "Balances", permission: "VIEW_FINANCIALS" },
  { to: "aging", label: "Aging", permission: "VIEW_FINANCIALS" },
  { to: "payment-behaviour", label: "Payment Behaviour", permission: "VIEW_FINANCIALS" },
  { to: "customers", label: "Customers", permission: "VIEW_FINANCIALS" },
  { to: "products", label: "Products", permission: "VIEW_FINANCIALS" },
  { to: "expenses", label: "Expenses", permission: "VIEW_FINANCIALS" },
  { to: "unclassified", label: "Unclassified Adjustments", permission: "VIEW_FINANCIALS" },
  { to: "stock", label: "Stock", permission: "VIEW_FINANCIALS" },
  { to: "sync", label: "Sync", permission: "RUN_SYNC" },
  { to: "agents", label: "Agents", permission: "VIEW_FINANCIALS" },
  { to: "reconciliation", label: "Reconciliation", permission: "VIEW_RECON_AND_DQ" },
  { to: "data-quality", label: "Data Quality", permission: "VIEW_RECON_AND_DQ" },
  { to: "settings", label: "Settings", permission: "MANAGE_SETTINGS" },
  { to: "users", label: "Users", permission: "MANAGE_USERS" },
];

export function CompanyLayout() {
  const { companyId = "" } = useParams();
  const location = useLocation();
  const company = useQuery({
    queryKey: [companyId, "/"], // under the company's key, so its actions refresh it too
    queryFn: () => api<Company>(`/companies/${companyId}`),
  });
  // FR-PAY-6: Payment Behaviour is listed only once its gate has passed (the page's own key)
  const payment = useQuery({
    queryKey: [companyId, "/analytics/payment-behaviour", {}],
    queryFn: () =>
      api<Schemas["PaymentBehaviourOut"]>(`/companies/${companyId}/analytics/payment-behaviour`),
    enabled: company.isSuccess && can(company.data, "VIEW_FINANCIALS"),
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
  // FR-4.3: moving between sections keeps the filters
  const keep = withFilters(readFilters(new URLSearchParams(location.search)));
  const nav = SECTIONS.filter(
    (s) =>
      can(company.data, s.permission) &&
      (s.to !== "payment-behaviour" || payment.data?.available === true),
  ).map((s) => ({ to: `/c/${companyId}/${s.to}${keep}`, label: s.label }));
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
