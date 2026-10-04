import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CHANGE_PASSWORD, RequireAuth } from "./components/RequireAuth";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { AgentsPage } from "./pages/AgentsPage";
import { AgingPage } from "./pages/AgingPage";
import {
  BalancesPage,
  CashFlowPage,
  ExpensesPage,
  PurchasesPage,
  SalesPage,
  UnclassifiedPage,
} from "./pages/AnalyticsPages";
import { DrilldownPage } from "./pages/DrilldownPage";
import { PaymentBehaviourPage } from "./pages/PaymentBehaviourPage";
import { CustomersPage, ProductsPage } from "./pages/RankingPage";
import { StockPage } from "./pages/StockPage";
import { VoucherPage } from "./pages/VoucherPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { CompanyLayout, RequirePermission, SECTIONS } from "./pages/CompanyLayout";
import { ForbiddenPage } from "./pages/ForbiddenPage";
import { DataQualityPage } from "./pages/DataQualityPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ReconciliationPage } from "./pages/ReconciliationPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SyncPage } from "./pages/SyncPage";
import { UsersPage } from "./pages/UsersPage";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
}

const PAGES: Record<string, ReactNode> = {
  home: <HomePage />,
  sales: <SalesPage />,
  purchases: <PurchasesPage />,
  "cash-flow": <CashFlowPage />,
  balances: <BalancesPage />,
  aging: <AgingPage />,
  "payment-behaviour": <PaymentBehaviourPage />,
  customers: <CustomersPage />,
  products: <ProductsPage />,
  expenses: <ExpensesPage />,
  unclassified: <UnclassifiedPage />,
  stock: <StockPage />,
  agents: <AgentsPage />,
  sync: <SyncPage />,
  settings: <SettingsPage />,
  users: <UsersPage />,
  "data-quality": <DataQualityPage />,
  reconciliation: <ReconciliationPage />,
};

/** A section not built yet shows its name. */
function Section({ title }: { title: string }) {
  return <h1 className="text-xl font-semibold">{title}</h1>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path={CHANGE_PASSWORD}
        element={
          <RequireAuth>
            <ChangePasswordPage />
          </RequireAuth>
        }
      />
      <Route
        path="/companies"
        element={
          <RequireAuth>
            <CompaniesPage />
          </RequireAuth>
        }
      />
      <Route
        path="/c/:companyId"
        element={
          <RequireAuth>
            <CompanyLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="home" replace />} />
        {SECTIONS.map((s) => (
          <Route
            key={s.to}
            path={`${s.to}/*`}
            element={
              <RequirePermission permission={s.permission}>
                {PAGES[s.to] ?? <Section title={s.label} />}
              </RequirePermission>
            }
          />
        ))}
        <Route
          path="analytics/:metric/drilldown"
          element={
            <RequirePermission permission="VIEW_FINANCIALS">
              <DrilldownPage />
            </RequirePermission>
          }
        />
        <Route
          path="vouchers/:voucherId"
          element={
            <RequirePermission permission="VIEW_FINANCIALS">
              <VoucherPage />
            </RequirePermission>
          }
        />
        <Route path="forbidden" element={<ForbiddenPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/companies" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
