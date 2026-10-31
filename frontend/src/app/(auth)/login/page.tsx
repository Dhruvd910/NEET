"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorBox, useHydrated } from "@/components/ui";
import { api, type Me } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const ready = useHydrated();

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const me = await api<Me>("/api/auth/login", { method: "POST", json: { email: f.get("email"), password: f.get("password") } });
      router.push(me.has_profile ? "/dashboard" : "/profile");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="h1 mb-4">Sign in</h1>
      <form method="post" onSubmit={submit} className="card space-y-3">
        <div><label className="label" htmlFor="email">Email</label><input className="input" id="email" name="email" type="email" required autoComplete="email" /></div>
        <div><label className="label" htmlFor="password">Password</label><input className="input" id="password" name="password" type="password" required autoComplete="current-password" /></div>
        <ErrorBox error={error} />
        <button className="btn w-full" disabled={busy || !ready}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="muted mt-3">New here? <Link className="text-teal-700 underline" href="/register">Create an account</Link></p>
    </div>
  );
}
