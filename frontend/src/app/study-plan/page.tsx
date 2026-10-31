"use client";

import Link from "next/link";
import { useState } from "react";
import { Calendar } from "@/components/icons";
import { ErrorBox, Loading, Notice, PageHeader, SignInPrompt, useApi } from "@/components/ui";
import { api, ApiError, fmtDate } from "@/lib/api";
import { type Chapter, SECTIONS } from "@/lib/practice";

type Task = { id: number; kind: string; title: string; detail: string | null; est_hours: number; chapter_id: number | null; status: string };
type Week = { week_index: number; week_start: string; phase: string; hours: number; tasks: Task[] };
type Plan = { id: number; current_class: string; start_date: string; exam_date: string; exam_date_is_estimate: boolean;
  weekday_hours: number; weekend_hours: number; current_week: number | null; progress: { done: number; total: number }; weeks: Week[];
  summary: { weeks: number; weekly_hours: number; final_phase_weeks: number; first_time_study_hours_needed: number;
    syllabus_finished_by: string | null; unfinished_chapters: string[]; weak_chapters: string[]; assumptions: string[]; warning?: string } };
type Progress = Record<string, { status: string | null; confidence: number | null; tests: { attempted: number; accuracy: number | null } | null }>;

const KIND_STYLE: Record<string, string> = {
  learn: "bg-sky-100 text-sky-900", revise: "bg-violet-100 text-violet-900", practice: "bg-amber-100 text-amber-900",
  mock: "bg-rose-100 text-rose-900", board: "bg-slate-200 text-slate-800",
};
const CLASS_LABEL: Record<string, string> = { "11": "Class 11", "12": "Class 12", dropper: "Dropper / repeater" };
const STATUS_LABEL: Record<string, string> = { not_started: "Not started", learning: "Studied once", revised: "Revised", mastered: "Confident" };

function TaskRow({ t, onToggle }: { t: Task; onToggle: (t: Task) => void }) {
  const link = t.kind === "mock" ? "/practice?mode=full" : t.kind === "practice" && t.title.startsWith("Weak") ? "/practice?mode=weak"
    : t.chapter_id && (t.kind === "learn" || t.kind === "revise") ? `/practice?chapter=${t.chapter_id}` : t.kind === "practice" ? "/practice?mode=chapter" : null;
  return (
    <li className="flex items-start gap-3 py-2">
      {t.kind !== "board" && (
        <input type="checkbox" className="mt-1" checked={t.status === "done"} onChange={() => onToggle(t)} aria-label={`Mark "${t.title}" done`} />)}
      <div className="min-w-0 flex-1">
        <p className={t.status === "done" ? "text-slate-400 line-through" : ""}>
          <span className={`mr-2 rounded px-1.5 py-0.5 text-[11px] font-medium capitalize ${KIND_STYLE[t.kind]}`}>{t.kind}</span>{t.title}</p>
        {t.detail && <p className="text-xs text-slate-500">{t.detail}</p>}
      </div>
      <div className="shrink-0 text-right text-xs text-slate-600">
        {t.est_hours > 0 && <p>{t.est_hours} h</p>}
        {link && <Link className="text-teal-700 underline" href={link}>{t.kind === "mock" || t.kind === "practice" ? "Start" : "Test"}</Link>}
      </div>
    </li>
  );
}

function PlanForm({ defaultClass, onCreated, compact }: { defaultClass: string | null; onCreated: (p: Plan) => void; compact?: boolean }) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      onCreated(await api<Plan>("/api/study-plan", { method: "POST", json: {
        current_class: f.get("current_class"), exam_date: f.get("exam_date") || null,
        weekday_hours: Number(f.get("weekday_hours")), weekend_hours: Number(f.get("weekend_hours")) } }));
    } catch (x) { setError(x); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className={`grid gap-3 ${compact ? "sm:grid-cols-5" : "card sm:grid-cols-2"}`}>
      {!compact && <h2 className="h2 sm:col-span-2">Build your plan</h2>}
      <label className="text-sm">Your class
        <select name="current_class" className="input mt-1" defaultValue={defaultClass ?? "12"} required>
          <option value="11">Class 11</option><option value="12">Class 12</option><option value="dropper">Dropper / repeater</option></select></label>
      <label className="text-sm">NEET date (leave empty to use an estimate)
        <input name="exam_date" type="date" className="input mt-1" /></label>
      <label className="text-sm">Study hours on a school/college day
        <input name="weekday_hours" type="number" step="0.5" min={0} max={12} defaultValue={4} className="input mt-1" required /></label>
      <label className="text-sm">Study hours on a weekend day
        <input name="weekend_hours" type="number" step="0.5" min={0} max={14} defaultValue={7} className="input mt-1" required /></label>
      <div className={compact ? "flex items-end" : "sm:col-span-2"}>
        <button className="btn" disabled={busy}>{busy ? "Building…" : compact ? "Rebuild plan" : "Build my plan"}</button></div>
      <div className={compact ? "sm:col-span-5" : "sm:col-span-2"}><ErrorBox error={error} /></div>
    </form>
  );
}

function SyllabusTracker() {
  const syl = useApi<{ chapters: Chapter[] }>("/api/syllabus");
  const prog = useApi<Progress>("/api/syllabus/progress");
  const [subject, setSubject] = useState<string>("Physics");
  if (!syl.data || !prog.data) return null;
  const set = async (id: number, status: string) => {
    await api(`/api/syllabus/progress/${id}`, { method: "PUT", json: { status } });
    prog.reload();
  };
  const chapters = syl.data.chapters.filter((c) => c.subject === subject);
  const counts = (s: string) => syl.data!.chapters.filter((c) => c.subject === s && ["revised", "mastered"].includes(prog.data![c.id]?.status ?? "")).length;

  return (
    <section className="card space-y-3">
      <div><h2 className="h2">Syllabus tracker</h2>
        <p className="muted text-sm">Mark where you are in each chapter, then rebuild your plan so it skips what you already know. Chapter list from the NEET-UG syllabus (pending verification against the current bulletin).</p></div>
      <div className="flex flex-wrap gap-2">{SECTIONS.map((s) => (
        <button key={s} onClick={() => setSubject(s)} aria-pressed={subject === s}
          className={`rounded-full px-3 py-1 text-xs ring-1 ${subject === s ? "bg-teal-700 text-white ring-teal-700" : "ring-slate-300"}`}>
          {s} · {counts(s)}/{syl.data!.chapters.filter((c) => c.subject === s).length}</button>))}</div>
      <ul className="divide-y divide-slate-100 text-sm">
        {chapters.map((c) => {
          const p = prog.data![c.id];
          return (
            <li key={c.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="min-w-0 flex-1">{c.name} <span className="text-xs text-slate-500">Class {c.class_level}</span>
                {p?.tests?.accuracy != null && <span className={`ml-2 text-xs ${p.tests.accuracy < 50 ? "text-red-700" : "text-slate-500"}`}>tests: {p.tests.accuracy}%</span>}</span>
              <select className="input !w-40 !py-1 text-xs" value={p?.status ?? "not_started"} onChange={(e) => set(c.id, e.target.value)}
                aria-label={`Status of ${c.name}`}>
                {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            </li>);
        })}
      </ul>
    </section>
  );
}

export default function StudyPlanPage() {
  const plan = useApi<Plan>("/api/study-plan");
  const profile = useApi<{ profile: { current_class: string | null } | null }>("/api/profile");
  const [override, setOverride] = useState<Plan | null>(null);
  const [showAll, setShowAll] = useState(false);
  const p = override ?? plan.data;

  if (plan.loading) return <Loading />;
  const noPlan = plan.error instanceof ApiError && plan.error.status === 404;
  if (plan.error && !noPlan && !override) return <SignInPrompt error={plan.error} />;
  const defaultClass = profile.data?.profile?.current_class ?? null;

  async function toggle(t: Task) {
    const status = t.status === "done" ? "todo" : "done";
    const before = override ?? plan.data!;
    // Update the tick straight away; the server response then brings the progress numbers.
    setOverride({ ...before, weeks: before.weeks.map((w) => ({ ...w, tasks: w.tasks.map((x) => (x.id === t.id ? { ...x, status } : x)) })) });
    try {
      await api(`/api/study-plan/tasks/${t.id}`, { method: "PATCH", json: { status } });
      setOverride(await api<Plan>("/api/study-plan"));
    } catch {
      setOverride(before);
      alert("Could not save. Check your connection and try again.");
    }
  }

  if (!p) return (
    <div className="space-y-5">
      <PageHeader icon={Calendar} eyebrow="Your study prescription" title="Study plan">A week-by-week NEET plan built around your class, the time left and how many hours you can study.</PageHeader>
      <PlanForm defaultClass={defaultClass} onCreated={setOverride} />
      <SyllabusTracker />
    </div>);

  const s = p.summary;
  const current = p.weeks.find((w) => w.week_index === p.current_week) ?? p.weeks[0];
  const upcoming = p.weeks.filter((w) => w.week_index > (current?.week_index ?? -1));
  const pct = p.progress.total ? Math.round((100 * p.progress.done) / p.progress.total) : 0;

  return (
    <div className="space-y-5">
      <PageHeader icon={Calendar} eyebrow="Your study prescription" title="Study plan">
        {CLASS_LABEL[p.current_class]} · NEET on {fmtDate(p.exam_date)}{p.exam_date_is_estimate && " (estimated)"} · {s.weeks} weeks · {s.weekly_hours} h/week
      </PageHeader>
      {s.warning && <Notice tone="warn">{s.warning}</Notice>}
      <section className="grid gap-3 sm:grid-cols-4">
        <div className="card"><p className="muted">Done</p><p className="text-xl font-semibold">{pct}%</p>
          <div className="mt-1 h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-teal-600" style={{ width: `${pct}%` }} /></div></div>
        <div className="card"><p className="muted">Syllabus finished by</p><p className="text-xl font-semibold">{s.syllabus_finished_by ? fmtDate(s.syllabus_finished_by) : "—"}</p></div>
        <div className="card"><p className="muted">Final revision & mocks</p><p className="text-xl font-semibold">{s.final_phase_weeks} weeks</p></div>
        <div className="card"><p className="muted">Weak chapters (from tests)</p><p className="text-xl font-semibold">{s.weak_chapters.length}</p></div>
      </section>

      {current && (
        <section className="card">
          <h2 className="h2">This week <span className="text-sm font-normal text-slate-500">from {fmtDate(current.week_start)} · {current.phase} · {current.hours} h</span></h2>
          <ul className="divide-y divide-slate-100 text-sm">{current.tasks.map((t) => <TaskRow key={t.id} t={t} onToggle={toggle} />)}</ul>
        </section>)}

      <section className="card">
        <div className="flex items-center justify-between"><h2 className="h2">Coming up</h2>
          <button className="text-sm text-teal-700 underline" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${upcoming.length} weeks`}</button></div>
        <div className="mt-2 space-y-2">
          {(showAll ? upcoming : upcoming.slice(0, 4)).map((w) => (
            <details key={w.week_index} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
              <summary className="cursor-pointer">
                <span className="font-medium">Week of {fmtDate(w.week_start)}</span> · {w.phase} · {w.hours} h ·{" "}
                <span className="text-slate-500">{w.tasks.filter((t) => t.kind === "learn").map((t) => t.title.replace("Learn: ", "")).slice(0, 3).join(", ") || w.tasks[0]?.title}</span>
              </summary>
              <ul className="divide-y divide-slate-100">{w.tasks.map((t) => <TaskRow key={t.id} t={t} onToggle={toggle} />)}</ul>
            </details>))}
        </div>
      </section>

      <section className="card text-sm">
        <h2 className="h2 mb-1">How this plan was made</h2>
        <ul className="list-disc space-y-1 pl-5 text-slate-700">{s.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        <div className="mt-3"><PlanForm defaultClass={p.current_class} onCreated={setOverride} compact /></div>
        <p className="mt-1 text-xs text-slate-500">Rebuilding keeps your syllabus progress but replaces the task list.</p>
      </section>

      <SyllabusTracker />
    </div>
  );
}
