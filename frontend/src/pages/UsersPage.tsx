import { useState, type FormEvent } from "react";
import type { Schemas } from "../api/types";
import { ScrollableTable } from "../components/ScrollableTable";
import { Badge } from "../components/ui";
import { ErrorText, fieldErrors, Loaded, useCompanyAction, useCompanyQuery } from "../lib/queries";

type User = Schemas["CompanyUserOut"];
type Role = Schemas["RoleName"];
const ROLES: Role[] = ["OWNER", "ADMIN", "ACCOUNTANT"];
const cell = "px-3 py-2 text-left align-top";
const input = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";

function RolePicker({ value, onChange }: { value: Role[]; onChange: (roles: Role[]) => void }) {
  return (
    <span className="flex flex-wrap gap-3">
      {ROLES.map((role) => (
        <label key={role} className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={value.includes(role)}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, role] : value.filter((r) => r !== role))
            }
          />
          {role}
        </label>
      ))}
    </span>
  );
}

/** RBAC-1.2: the company's users and their roles (Owner only). */
export function UsersPage() {
  const users = useCompanyQuery<User[]>("/users");
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Users</h1>
      <Loaded query={users} label="Loading users">
        {(list) => (
          <ScrollableTable caption="Users of this company">
            <thead className="bg-slate-50">
              <tr>
                <th className={cell}>Name</th>
                <th className={cell}>Email</th>
                <th className={cell}>Roles</th>
              </tr>
            </thead>
            <tbody>
              {list.map((u) => (
                <UserRow key={u.user_id} user={u} />
              ))}
            </tbody>
          </ScrollableTable>
        )}
      </Loaded>
      <AddUser />
    </section>
  );
}

function UserRow({ user }: { user: User }) {
  const [roles, setRoles] = useState<Role[] | null>(null);
  const update = useCompanyAction<User, Role[]>((next) => ({
    path: `/users/${user.user_id}`,
    method: "PUT",
    body: { roles: next },
  }));
  return (
    <tr className="border-t border-slate-200">
      <td className={cell}>
        {user.name} {!user.is_active && <Badge>inactive</Badge>}
      </td>
      <td className={`${cell} break-all`}>{user.email}</td>
      <td className={cell}>
        {roles === null ? (
          <>
            {user.roles.join(", ") || "no role"}{" "}
            <button type="button" className="underline" onClick={() => setRoles(user.roles)}>
              Change
            </button>
          </>
        ) : (
          <div className="space-y-1">
            <RolePicker value={roles} onChange={setRoles} />
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded bg-slate-800 px-2 py-1 text-sm text-white"
                onClick={() => update.mutate(roles, { onSuccess: () => setRoles(null) })}
              >
                Save roles
              </button>
              <button type="button" className="px-2 py-1 text-sm" onClick={() => setRoles(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        <ErrorText error={update.error} />
      </td>
    </tr>
  );
}

function AddUser() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<Role[]>(["ACCOUNTANT"]);
  const add = useCompanyAction<User, Schemas["UserCreate"]>((body) => ({ path: "/users", body }));
  const errors = fieldErrors(add.error);
  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(
      { email: email.trim(), name: name.trim(), password, roles },
      {
        onSuccess: () => {
          setEmail("");
          setName("");
          setPassword("");
        },
      },
    );
  }
  return (
    <form
      onSubmit={submit}
      className="grid gap-2 rounded border border-slate-200 bg-white p-3 sm:grid-cols-2"
    >
      <h2 className="font-semibold sm:col-span-2">Add a user</h2>
      <label className="text-sm">
        Email
        <input
          type="email"
          required
          className={input}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {errors.email && (
          <span role="alert" className="block text-red-800">
            {errors.email}
          </span>
        )}
      </label>
      <label className="text-sm">
        Name
        <input required className={input} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="text-sm sm:col-span-2">
        Initial password (at least 8 characters)
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          className={input}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <span className="block text-slate-600">
          It works once: at first sign-in they must choose their own. Someone who already has an
          account keeps their password and is simply given access to this company.
        </span>
        {errors.password && (
          <span role="alert" className="block text-red-800">
            {errors.password}
          </span>
        )}
      </label>
      <div className="text-sm sm:col-span-2">
        Roles <RolePicker value={roles} onChange={setRoles} />
      </div>
      <div className="space-y-1 sm:col-span-2">
        {Object.keys(errors).length === 0 && <ErrorText error={add.error} />}
        {add.isSuccess && (
          <p role="status" className="text-sm text-green-800">
            Added.
          </p>
        )}
        <button
          type="submit"
          disabled={roles.length === 0 || add.isPending}
          className="rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-50"
        >
          Add user
        </button>
      </div>
    </form>
  );
}
