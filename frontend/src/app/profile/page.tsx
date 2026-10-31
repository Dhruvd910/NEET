"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BadgeId } from "@/components/icons";
import { ErrorBox, Loading, Notice, PageHeader, SignInPrompt, useApi } from "@/components/ui";
import { api, CATEGORIES, STATES } from "@/lib/api";

type Profile = Record<string, unknown> & { preferred_states: string[]; institution_preferences: string[] };
type Exam = { exam_year: number; has_taken: boolean; score: number | null; air: number | null; state_rank: number | null;
  rank_type: "official" | "estimated"; estimated_rank_low: number | null; estimated_rank_high: number | null; percentile: number | null };
type ProfileResp = { profile: Profile | null; exams: Exam[] };

const val = (f: FormData, k: string) => { const v = f.get(k); return v === null || v === "" ? null : String(v); };
const numOrNull = (f: FormData, k: string) => { const v = val(f, k); return v === null ? null : Number(v); };
const THIS_YEAR = new Date().getFullYear();

export default function ProfilePage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<ProfileResp>("/api/profile");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [rankType, setRankType] = useState<"official" | "estimated" | null>(null);
  const [taken, setTaken] = useState<boolean | null>(null);

  if (loading) return <Loading />;
  if (error) return <SignInPrompt error={error} />;
  const p = data?.profile ?? ({ preferred_states: [], institution_preferences: [] } as unknown as Profile);
  const exam = data?.exams.at(-1);
  const rt = rankType ?? exam?.rank_type ?? "official";
  const hasTaken = taken ?? exam?.has_taken ?? false;

  async function saveProfile(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setErr(null);
    try {
      await api("/api/profile", { method: "PUT", json: {
        display_name: val(f, "display_name"), current_class: val(f, "current_class"), academic_year: val(f, "academic_year"),
        state: val(f, "state"), domicile_state: val(f, "domicile_state"), class10_percentage: numOrNull(f, "class10_percentage"),
        class12_status: val(f, "class12_status"), category: val(f, "category"), pwd: f.get("pwd") === "on",
        preferred_course: val(f, "preferred_course"), preferred_states: f.getAll("preferred_states").map(String),
        institution_preferences: f.getAll("institution_preferences").map(String),
        budget_max_annual: numOrNull(f, "budget_max_annual"), hostel_required: f.get("hostel_required") === "on",
      } });
      setMsg("Profile saved.");
      reload();
    } catch (x) { setErr(x); }
  }

  async function saveExam(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setErr(null);
    try {
      await api("/api/exam-profiles", { method: "PUT", json: {
        exam_year: numOrNull(f, "exam_year"), has_taken: hasTaken, score: numOrNull(f, "score"),
        percentile: numOrNull(f, "percentile"), rank_type: rt,
        air: rt === "official" ? numOrNull(f, "air") : null, state_rank: rt === "official" ? numOrNull(f, "state_rank") : null,
        estimated_rank_low: rt === "estimated" ? numOrNull(f, "estimated_rank_low") : null,
        estimated_rank_high: rt === "estimated" ? numOrNull(f, "estimated_rank_high") : null,
      } });
      setMsg("Exam details saved.");
      reload();
    } catch (x) { setErr(x); }
  }

  async function exportData() {
    const d = await api("/api/auth/me/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "my-neet-compass-data.json" });
    a.click();
    URL.revokeObjectURL(url);
  }

  async function deleteAccount() {
    if (!confirm("Permanently delete your account and all your data? This cannot be undone.")) return;
    await api("/api/auth/me", { method: "DELETE" });
    router.push("/");
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={BadgeId} eyebrow="Student record" title="Your profile">Fill in only what you need now — you can come back any time.</PageHeader>
      {msg && <Notice>{msg}</Notice>}
      <ErrorBox error={err} />

      <form method="post" onSubmit={saveProfile} className="card grid gap-4 sm:grid-cols-2">
        <h2 className="h2 sm:col-span-2">About you</h2>
        <div><label className="label" htmlFor="display_name">Display name</label><input id="display_name" name="display_name" className="input" defaultValue={(p.display_name as string) ?? ""} /></div>
        <div><label className="label" htmlFor="current_class">Current stage</label>
          <select id="current_class" name="current_class" className="input" defaultValue={(p.current_class as string) ?? ""}>
            <option value="">Choose…</option><option value="11">Class 11</option><option value="12">Class 12</option>
            <option value="dropper">Repeating / dropper year</option><option value="graduated">Finished class 12</option><option value="other">Other</option>
          </select></div>
        <div><label className="label" htmlFor="state">State you live in</label>
          <select id="state" name="state" className="input" defaultValue={(p.state as string) ?? ""}><option value="">Choose…</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div><label className="label" htmlFor="domicile_state">Domicile state (for state quota)</label>
          <select id="domicile_state" name="domicile_state" className="input" defaultValue={(p.domicile_state as string) ?? ""}><option value="">Not sure / not needed yet</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div><label className="label" htmlFor="class10_percentage">Class 10 percentage (optional)</label><input id="class10_percentage" name="class10_percentage" type="number" step="0.1" min={0} max={100} className="input" defaultValue={(p.class10_percentage as number) ?? ""} /></div>
        <div><label className="label" htmlFor="academic_year">Academic year</label><input id="academic_year" name="academic_year" placeholder="e.g. 2025-26" className="input" defaultValue={(p.academic_year as string) ?? ""} /></div>

        <h2 className="h2 mt-2 sm:col-span-2">Admission preferences</h2>
        <div><label className="label" htmlFor="preferred_course">Preferred course</label>
          <select id="preferred_course" name="preferred_course" className="input" defaultValue={(p.preferred_course as string) ?? "MBBS"}>
            <option>MBBS</option><option>BDS</option><option>BAMS</option><option>BHMS</option></select></div>
        <div><label className="label" htmlFor="budget_max_annual">Max yearly budget in ₹ (optional)</label><input id="budget_max_annual" name="budget_max_annual" type="number" min={0} step={10000} className="input" defaultValue={(p.budget_max_annual as number) ?? ""} /></div>
        <fieldset className="sm:col-span-2"><legend className="label">Institution types you would consider</legend>
          <div className="flex flex-wrap gap-4 text-sm">{["government", "central", "private", "deemed"].map((t) => (
            <label key={t} className="flex items-center gap-2 capitalize"><input type="checkbox" name="institution_preferences" value={t} defaultChecked={p.institution_preferences.includes(t)} />{t}</label>))}</div></fieldset>
        <div className="sm:col-span-2"><label className="label" htmlFor="preferred_states">Preferred states (Ctrl/⌘-click for several)</label>
          <select id="preferred_states" name="preferred_states" multiple className="input h-28" defaultValue={p.preferred_states}>{STATES.map((s) => <option key={s}>{s}</option>)}</select></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="hostel_required" defaultChecked={!!p.hostel_required} /> I need hostel accommodation</label>

        <details className="rounded-lg border border-slate-200 p-3 sm:col-span-2">
          <summary className="cursor-pointer text-sm font-medium">Category details (only needed for college matching)</summary>
          <p className="muted mt-2">Counselling rules reserve seats by category, so we need this to compare you with the right cutoffs. It is private, never shown to anyone, and never used to judge you.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div><label className="label" htmlFor="category">Category</label>
              <select id="category" name="category" className="input" defaultValue={(p.category as string) ?? ""}><option value="">Prefer not to say (compare with OPEN)</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="pwd" defaultChecked={!!p.pwd} /> Person with benchmark disability (PwD)</label>
          </div>
        </details>
        <div className="sm:col-span-2"><button className="btn">Save profile</button></div>
      </form>

      <form method="post" onSubmit={saveExam} className="card grid gap-4 sm:grid-cols-2">
        <h2 className="h2 sm:col-span-2">NEET details</h2>
        <div><label className="label" htmlFor="exam_year">NEET exam year</label><input id="exam_year" name="exam_year" type="number" required min={2015} max={2100} className="input" defaultValue={exam?.exam_year ?? THIS_YEAR} /></div>
        <fieldset><legend className="label">Have you taken this NEET?</legend>
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-2"><input type="radio" name="taken" checked={hasTaken} onChange={() => setTaken(true)} /> Yes</label>
            <label className="flex items-center gap-2"><input type="radio" name="taken" checked={!hasTaken} onChange={() => setTaken(false)} /> Not yet</label>
          </div></fieldset>
        {hasTaken && (<>
          <div><label className="label" htmlFor="score">Score (out of 720, if known)</label><input id="score" name="score" type="number" min={-180} max={720} className="input" defaultValue={exam?.score ?? ""} /></div>
          <div><label className="label" htmlFor="percentile">Percentile (if known)</label><input id="percentile" name="percentile" type="number" step="0.0000001" min={0} max={100} className="input" defaultValue={exam?.percentile ?? ""} /></div>
          <fieldset className="sm:col-span-2"><legend className="label">Is your rank official or an estimate?</legend>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="radio" name="rt" checked={rt === "official"} onChange={() => setRankType("official")} /> Official (published by NTA / state authority)</label>
              <label className="flex items-center gap-2"><input type="radio" name="rt" checked={rt === "estimated"} onChange={() => setRankType("estimated")} /> Estimated (results not out yet)</label>
            </div></fieldset>
          {rt === "official" ? (<>
            <div><label className="label" htmlFor="air">All India Rank (AIR)</label><input id="air" name="air" type="number" min={1} className="input" defaultValue={exam?.air ?? ""} /></div>
            <div><label className="label" htmlFor="state_rank">State rank (if published)</label><input id="state_rank" name="state_rank" type="number" min={1} className="input" defaultValue={exam?.state_rank ?? ""} /></div>
          </>) : (<>
            <Notice tone="warn">Enter a range, not a single number. Results using an estimate are clearly labelled and less certain.</Notice>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="label" htmlFor="estimated_rank_low">Best-case AIR</label><input id="estimated_rank_low" name="estimated_rank_low" type="number" min={1} className="input" defaultValue={exam?.estimated_rank_low ?? ""} /></div>
              <div><label className="label" htmlFor="estimated_rank_high">Worst-case AIR</label><input id="estimated_rank_high" name="estimated_rank_high" type="number" min={1} className="input" defaultValue={exam?.estimated_rank_high ?? ""} /></div>
            </div>
          </>)}
        </>)}
        <div className="sm:col-span-2"><button className="btn">Save NEET details</button></div>
      </form>

      <section className="card space-y-2">
        <h2 className="h2">Your data</h2>
        <p className="muted">Download everything we store about you, or delete your account permanently.</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={exportData}>Download my data</button>
          <button className="btn-secondary !border-red-300 !text-red-700" onClick={deleteAccount}>Delete my account</button>
        </div>
      </section>
    </div>
  );
}
