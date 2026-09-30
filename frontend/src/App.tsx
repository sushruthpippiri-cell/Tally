import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { RequireAuth } from "./components/RequireAuth";
import { logout } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
}

function SignOut() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      className="rounded border border-slate-300 px-3 py-1"
      onClick={() => void logout().then(() => navigate("/login", { replace: true }))}
    >
      Sign out
    </button>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/companies"
        element={
          <RequireAuth>
            <main className="p-4">
              <h1 className="text-xl font-semibold">Companies</h1>
              <SignOut />
            </main>
          </RequireAuth>
        }
      />
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
