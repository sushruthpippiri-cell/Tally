import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { CHANGE_PASSWORD, RequireAuth } from "./components/RequireAuth";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { CompanyLayout, RequirePermission, SECTIONS } from "./pages/CompanyLayout";
import { ForbiddenPage } from "./pages/ForbiddenPage";
import { LoginPage } from "./pages/LoginPage";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
}

/** Until P13.6-P13.10 build them, each section shows its name. */
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
                <Section title={s.label} />
              </RequirePermission>
            }
          />
        ))}
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
