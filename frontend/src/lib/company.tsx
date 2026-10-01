import { createContext, useContext, type ReactNode } from "react";
import type { Schemas } from "../api/types";

export type Company = Schemas["CompanyOut"];

const CompanyContext = createContext<Company | null>(null);

/** The company being viewed: its time zone (every date shown uses it, TZ-1.1) and what the
 * user may do in it. Hiding what the user cannot do is convenience only: the API enforces
 * every permission itself (RBAC-1.1). */
export function CompanyProvider({ company, children }: { company: Company; children: ReactNode }) {
  return <CompanyContext.Provider value={company}>{children}</CompanyContext.Provider>;
}

export function useCompany(): Company {
  const company = useContext(CompanyContext);
  if (company === null) throw new Error("useCompany outside a company route");
  return company;
}

export function can(company: Company, permission: string): boolean {
  return company.my_permissions.includes(permission);
}
