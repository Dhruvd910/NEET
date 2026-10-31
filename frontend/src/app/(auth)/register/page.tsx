"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorBox, useHydrated } from "@/components/ui";
import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [minor, setMinor] = useState<boolean | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const ready = useHydrated();

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await api("/api/auth/register", {
        method: "POST",
        json: {
          email: f.get("email"), password: f.get("password"), is_minor: minor === true,
          guardian_email: minor ? f.get("guardian_email") : null, accept_privacy_notice: f.get("privacy") === "on",
        },
      });
      router.push("/profile");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="h1 mb-1">Create your account</h1>
      <p className="muted mb-4">We only ask for what we need. You can export or delete your data at any time.</p>
      <form method="post" onSubmit={submit} className="card space-y-4">
        <div><label className="label" htmlFor="email">Email</label><input className="input" id="email" name="email" type="email" required autoComplete="email" /></div>
        <div><label className="label" htmlFor="password">Password (min. 8 characters)</label><input className="input" id="password" name="password" type="password" minLength={8} required autoComplete="new-password" /></div>
        <fieldset>
          <legend className="label">Are you under 18?</legend>
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-2"><input type="radio" name="minor" required onChange={() => setMinor(true)} /> Yes</label>
            <label className="flex items-center gap-2"><input type="radio" name="minor" onChange={() => setMinor(false)} /> No</label>
          </div>
        </fieldset>
        {minor && (
          <div className="space-y-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            <label className="label !text-amber-900" htmlFor="guardian_email">Parent or guardian&apos;s email</label>
            <input className="input" id="guardian_email" name="guardian_email" type="email" required />
            <p>
              We&apos;ll email them a link to review what we collect and give consent. Until they do, we won&apos;t store
              your profile, ranks, mock tests or chats. Without consent the account is deleted after 7 days.
            </p>
          </div>
        )}
        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input type="checkbox" name="privacy" required className="mt-1" />
          <span>
            I have read the privacy notice: my marks, rank and category are private, used only for my guidance, never
            shown publicly or sold, and I can delete them any time.
          </span>
        </label>
        <ErrorBox error={error} />
        <button className="btn w-full" disabled={busy || !ready}>{busy ? "Creating…" : "Create account"}</button>
      </form>
      <p className="muted mt-3">Already registered? <Link className="text-teal-700 underline" href="/login">Sign in</Link></p>
    </div>
  );
}
