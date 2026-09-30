import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

export interface NavItem {
  to: string;
  label: string;
}

/** Sidebar from the `md` breakpoint up; below it, a top bar with a menu drawer (NFR-UI-1). */
export function Shell({
  title,
  nav,
  actions,
  children,
}: {
  title: string;
  nav: NavItem[];
  actions?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const links = (
    <ul className="space-y-1">
      {nav.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            onClick={() => setOpen(false)}
            className={({ isActive }) =>
              `block rounded px-3 py-2 ${isActive ? "bg-slate-800 text-white" : "hover:bg-slate-200"}`
            }
          >
            {item.label}
          </NavLink>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 md:flex">
      <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white p-3 md:block">
        <p className="mb-3 truncate px-3 font-semibold">{title}</p>
        <nav aria-label="Sections">{links}</nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2">
          <button
            type="button"
            className="rounded px-2 py-1 md:hidden"
            aria-expanded={open}
            aria-controls="nav-drawer"
            onClick={() => setOpen(!open)}
          >
            Menu
          </button>
          <p className="min-w-0 truncate font-semibold md:hidden">{title}</p>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </header>
        {open && (
          <nav
            id="nav-drawer"
            aria-label="Sections"
            className="border-b border-slate-200 bg-white p-3 md:hidden"
          >
            {links}
          </nav>
        )}
        <main className="mx-auto max-w-6xl p-3 md:p-6">{children}</main>
      </div>
    </div>
  );
}
