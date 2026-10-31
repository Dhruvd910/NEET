"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ErrorBox, Loading } from "@/components/ui";
import { api } from "@/lib/api";

type Info = { student_email: string; status: string; notice_version: string };

const COLLECTED = [
  ["Account", "Email address and password (stored as a one-way hash)."],
  ["Profile", "Class, state, domicile, preferred courses and states, budget. Category and PwD status only if the student enters them, used only to compare with the matching cutoffs."],
  ["Exam data", "NEET rank or an estimated rank range, and mock-test scores the student enters."],
  ["Usage", "Saved colleges, comparisons, draft preference lists and assistant chats."],
];

function ConsentForm() {
  const token = useSearchParams().get("token") ?? "";
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      setError(new Error("This link is missing its token. Open the link from the email again."));
      return;
    }
    api<Info>(`/api/auth/guardian-consent/${encodeURIComponent(token)}`).then(setInfo).catch(setError);
  }, [token]);

  async function decide(e: React.FormEvent<HTMLFormElement>, decision: "approve" | "decline") {
    e.preventDefault();
    const form = (e.currentTarget.closest("form") ?? e.currentTarget) as HTMLFormElement;
    if (!form.reportValidity()) return;
    const f = new FormData(form);
    setBusy(true);
    try {
      const r = await api<{ status: string }>(`/api/auth/guardian-consent/${encodeURIComponent(token)}`, {
        method: "POST",
        json: { decision, guardian_name: f.get("guardian_name"), relationship: f.get("relationship"),
                confirm_is_guardian: f.get("confirm") === "on" },
      });
      setDone(r.status);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <div className="card">
        <h1 className="h1 mb-2">{done === "verified" ? "Thank you — consent recorded" : "Consent declined"}</h1>
        <p className="muted">
          {done === "verified"
            ? "The student can now use all features. You or the student can download or delete the data at any time from the profile page."
            : "We will not store any personal data for this account, and it will be deleted automatically."}
        </p>
      </div>
    );
  if (error) return <ErrorBox error={error} />;
  if (!info) return <Loading />;

  return (
    <form method="post" className="card space-y-4" onSubmit={(e) => decide(e, "approve")}>
      <h1 className="h1">Parent or guardian consent</h1>
      <p>
        A student account (<strong>{info.student_email}</strong>) named you as their parent or guardian. Because the
        student is under 18, we need your consent before we store their personal information.
      </p>
      <section>
        <h2 className="h2 mb-1">What we would store</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          {COLLECTED.map(([k, v]) => <li key={k}><strong>{k}:</strong> {v}</li>)}
        </ul>
      </section>
      <section className="text-sm text-slate-700">
        <h2 className="h2 mb-1">How it is used</h2>
        <p>
          Only to give this student guidance: college matching against past cutoffs, cost estimates, mock-test trends
          and answers from official documents. It is never sold, never shown publicly and never used for advertising
          or tracking. The student (or you) can download or permanently delete it at any time.
        </p>
      </section>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label" htmlFor="guardian_name">Your full name</label>
          <input className="input" id="guardian_name" name="guardian_name" required minLength={2} /></div>
        <div><label className="label" htmlFor="relationship">Relationship to the student</label>
          <select className="input" id="relationship" name="relationship" required defaultValue="">
            <option value="" disabled>Choose…</option><option>mother</option><option>father</option>
            <option>legal guardian</option></select></div>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" name="confirm" required className="mt-1" />
        I am this student&apos;s parent or legal guardian, and I have read the above (notice version {info.notice_version}).
      </label>
      <div className="flex flex-wrap gap-2">
        <button className="btn" disabled={busy}>I give consent</button>
        <button type="button" className="btn-secondary" disabled={busy}
          onClick={(e) => decide(e as unknown as React.FormEvent<HTMLFormElement>, "decline")}>I do not consent</button>
      </div>
    </form>
  );
}

export default function GuardianConsentPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <Suspense fallback={<Loading />}><ConsentForm /></Suspense>
    </div>
  );
}
