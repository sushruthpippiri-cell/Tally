import { Link } from "react-router-dom";

export function ForbiddenPage() {
  return (
    <main className="mx-auto max-w-md space-y-3 p-4">
      <h1 className="text-xl font-semibold">Not available to you</h1>
      <p className="text-slate-700">
        Your role in this company does not include this. An Owner can change your role in Users.
      </p>
      <Link to="/companies" className="underline">
        Back to your companies
      </Link>
    </main>
  );
}
