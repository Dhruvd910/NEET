"use client";

import Link from "next/link";
import { useState } from "react";
import { Stethoscope } from "@/components/icons";
import { CollegeCard, Empty, Loading, PageHeader, SignInPrompt, useApi } from "@/components/ui";
import { api, type CollegeCardT, type Me } from "@/lib/api";

type Roadmap = { id: number; title: string; detail: string | null; kind: string; status: string }[];
type Analytics = { count: number; latest_percent?: number; average_percent?: number; trend: { direction: string } | null; notice: string };
type ProfileResp = { profile: { display_name: string | null } | null; exams: { exam_year: number; air: number | null; rank_type: string }[] };

export default function Dashboard() {
  const me = useApi<Me>("/api/auth/me");
  const authed = !!me.data;
  const profile = useApi<ProfileResp>(authed ? "/api/profile" : null);
  const roadmap = useApi<Roadmap>(authed ? "/api/roadmap" : null);
  const mocks = useApi<Analytics>(authed ? "/api/mock-tests/analytics" : null);
  const saved = useApi<{ college: CollegeCardT }[]>(authed ? "/api/saved-colleges" : null);
  const [busy, setBusy] = useState(false);

  if (me.loading) return <Loading />;
  if (me.error) return <SignInPrompt error={me.error} />;

  async function generate() {
    setBusy(true);
    try { roadmap.setData(await api<Roadmap>("/api/roadmap/generate", { method: "POST" })); } finally { setBusy(false); }
  }
  async function setStatus(id: number, status: string) {
    await api(`/api/roadmap/${id}`, { method: "PATCH", json: { status } });
    roadmap.reload();
  }

  const exam = profile.data?.exams.at(-1);
  return (
    <div className="space-y-6">
      <PageHeader icon={Stethoscope} eyebrow="Future doctor's desk" title={`Hello, future Dr.${profile.data?.profile?.display_name ? ` ${profile.data.profile.display_name}` : ""}`}>
        Your NEET journey at a glance.
      </PageHeader>

      {!profile.loading && !profile.data?.profile && (
        <Empty title="Complete your profile to personalise everything"><Link className="text-teal-700 underline" href="/profile">Set up your profile</Link></Empty>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="card">
          <p className="muted">NEET {exam?.exam_year ?? ""}</p>
          <p className="mt-1 text-2xl font-semibold">{exam?.air ? `AIR ${exam.air.toLocaleString("en-IN")}` : "No rank yet"}</p>
          <p className="text-xs text-slate-500">{exam?.air ? (exam.rank_type === "official" ? "Official rank" : "Estimated") : <Link className="underline" href="/profile">Add NEET details</Link>}</p>
          <Link href="/predictor" className="btn mt-3">Check college matches</Link>
        </div>
        <div className="card">
          <p className="muted">Mock tests</p>
          {mocks.data?.count ? (<>
            <p className="mt-1 text-2xl font-semibold">{mocks.data.latest_percent}% <span className="text-sm font-normal text-slate-500">latest</span></p>
            <p className="text-xs text-slate-500">Average {mocks.data.average_percent}% · trend {mocks.data.trend?.direction ?? "—"}</p>
          </>) : <p className="mt-1 text-sm">No tests logged yet.</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <Link href="/practice" className="btn">Take a test</Link>
            <Link href="/study-plan" className="btn-secondary">Study plan</Link>
            <Link href="/mock-tests" className="btn-secondary">Tracker</Link>
          </div>
        </div>
        <div className="card">
          <p className="muted">Shortlist</p>
          <p className="mt-1 text-2xl font-semibold">{saved.data?.length ?? 0} colleges</p>
          <Link href="/compare" className="btn-secondary mt-3">Compare</Link>
        </div>
      </div>

      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="h2">Your roadmap</h2>
          <button className="btn-secondary" onClick={generate} disabled={busy}>{busy ? "Updating…" : roadmap.data?.length ? "Refresh suggestions" : "Generate my roadmap"}</button>
        </div>
        {roadmap.loading ? <Loading /> : roadmap.data?.length ? (
          <ul className="mt-3 divide-y divide-slate-100">
            {roadmap.data.map((i) => (
              <li key={i.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
                <div>
                  <p className={`font-medium ${i.status === "done" ? "text-slate-400 line-through" : ""}`}>{i.title} <span className="ml-1 rounded bg-slate-100 px-1.5 text-xs font-normal capitalize text-slate-600">{i.kind}</span></p>
                  {i.detail && <p className="text-sm text-slate-600">{i.detail}</p>}
                </div>
                <select aria-label={`Status of ${i.title}`} className="input !w-auto" value={i.status} onChange={(e) => setStatus(i.id, e.target.value)}>
                  <option value="todo">To do</option><option value="doing">Doing</option><option value="done">Done</option>
                </select>
              </li>
            ))}
          </ul>
        ) : <p className="muted mt-2">Generate a roadmap based on your profile and mock tests. Official dates are never guessed — each step points to the authority that announces them.</p>}
      </section>

      {!!saved.data?.length && (
        <section>
          <h2 className="h2 mb-3">Saved colleges</h2>
          <div className="grid gap-4 md:grid-cols-2">{saved.data.map((s) => <CollegeCard key={s.college.id} c={s.college} />)}</div>
        </section>
      )}
    </div>
  );
}
