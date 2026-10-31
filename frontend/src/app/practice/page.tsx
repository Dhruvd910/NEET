"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Clipboard, Clock, HeartPulse, Sparkle, Target } from "@/components/icons";
import { ErrorBox, Loading, Notice, PageHeader, SignInPrompt, SubjectBadge, SUBJECT_STYLE, useApi } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { type AttemptSummary, type Bank, type Chapter, type Pattern, type Readiness, SECTIONS } from "@/lib/practice";

type Mode = "full" | "mini" | "subject" | "chapter" | "weak";
type Perf = { chapters: { chapter_id: number; chapter: string; subject: string; attempted: number; correct: number; accuracy: number | null }[]; note: string };
type Preparing = { status: "preparing"; detail: string; needed: Record<string, number>; generating: boolean };

const MODE_INFO: Record<Mode, { title: string; text: string; icon: (p: { className?: string }) => React.ReactElement }> = {
  full: { title: "Full NEET mock", text: "180 questions · 3 hours · exam-day flow with admit card and OMR sheet.", icon: Clipboard },
  mini: { title: "Mini NEET mock", text: "Same format and 1 minute per question, fewer questions per section.", icon: Clock },
  subject: { title: "Subject practice", text: "One subject, timed at 1 minute per question.", icon: Sparkle },
  chapter: { title: "Chapter / topic test", text: "Pick up to 10 chapters.", icon: Target },
  weak: { title: "My weak chapters", text: "Chapters where you scored under 60% before.", icon: HeartPulse },
};

function Builder() {
  const router = useRouter();
  const params = useSearchParams();
  const pat = useApi<{ pattern: Pattern; bank: Bank }>("/api/exams/pattern");
  const syl = useApi<{ chapters: Chapter[] }>("/api/syllabus");
  const attempts = useApi<AttemptSummary[]>("/api/exams/attempts");
  const ready = useApi<Readiness>(attempts.data ? "/api/exams/readiness" : null);
  const perf = useApi<Perf>(attempts.data ? "/api/exams/performance" : null);
  const preChapter = Number(params.get("chapter")) || null;
  const [mode, setMode] = useState<Mode | null>(preChapter ? "chapter" : (params.get("mode") as Mode | null));
  const [subject, setSubject] = useState("Physics");
  const [perSection, setPerSection] = useState(10);
  const [count, setCount] = useState(20);
  const [chapterIds, setChapterIds] = useState<number[]>(preChapter ? [preChapter] : []);
  const [chapterSubject, setChapterSubject] = useState<string>("Physics");
  const [strict, setStrict] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState<Preparing | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  const preSubject = useMemo(() => syl.data?.chapters.find((c) => c.id === preChapter)?.subject, [syl.data, preChapter]);
  useEffect(() => { if (preSubject) setChapterSubject(preSubject); }, [preSubject]);

  // While fresh questions are being written, refresh the counts so students see progress.
  const generating = ready.data?.generating;
  const reloadReady = ready.reload;
  useEffect(() => {
    if (!generating && !preparing) return;
    const t = setInterval(reloadReady, 6000);
    return () => clearInterval(t);
  }, [generating, preparing, reloadReady]);
  useEffect(() => () => { if (retry.current) clearTimeout(retry.current); }, []);

  const body = useCallback(() => {
    const b: Record<string, unknown> = { mode, strict_omr: strict };
    if (mode === "mini") b.count = perSection;
    if (mode === "subject") Object.assign(b, { subject, count });
    if (mode === "chapter") Object.assign(b, { chapter_ids: chapterIds, count });
    if (mode === "weak") b.count = count;
    return b;
  }, [mode, strict, perSection, subject, count, chapterIds]);

  const prepare = useCallback(async function prepareRun() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<AttemptSummary | Preparing>("/api/exams/attempts", { method: "POST", json: body() });
      if ("status" in r && r.status === "preparing") {
        // Fresh questions are being written and checked; try again shortly.
        setPreparing(r as Preparing);
        retry.current = setTimeout(prepareRun, 10000);
        return;
      }
      setPreparing(null);
      router.push(`/practice/${(r as AttemptSummary).id}`);
    } catch (e) {
      setPreparing(null);
      setError(e);
      setBusy(false);
    }
  }, [body, router]);

  if (pat.loading || attempts.loading) return <Loading label="Opening the exam hall…" />;
  if (attempts.error) return <SignInPrompt error={attempts.error} />;
  const { pattern } = pat.data!;
  const inProgress = attempts.data?.find((a) => a.status === "in_progress");
  const r = ready.data;
  const fullPossible = !r || r.full_mocks_available > 0 || r.can_generate;

  return (
    <div className="space-y-6">
      <PageHeader icon={Clipboard} eyebrow="Exam hall" title="NEET practice tests">
        Real exam-day practice: admit card, instructions, a sealed booklet and an OMR sheet. Every paper is made of
        questions you have <strong>never seen before</strong>.
      </PageHeader>

      {inProgress && (
        <Notice tone="warn">
          You have a test in progress: <strong>{inProgress.title}</strong>.{" "}
          <Link className="underline" href={`/practice/${inProgress.id}`}>Resume it</Link> (the clock keeps running).
        </Notice>)}

      <section className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <div className="card relative overflow-hidden">
          <div aria-hidden="true" className="med-pattern pointer-events-none absolute inset-0 opacity-50 [mask-image:linear-gradient(to_left,black,transparent_70%)]" />
          <div className="relative">
            <h2 className="h2">Fresh questions waiting for you</h2>
            <p className="muted mt-0.5">Questions you have not seen in any earlier test. Papers never repeat a question.</p>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {SECTIONS.map((s) => (
                <div key={s} className="rounded-xl border border-slate-200 bg-white/80 p-3">
                  <SubjectBadge subject={s} />
                  <p className="mt-2 text-2xl font-bold tabular-nums">{r ? r.unseen[s] ?? 0 : "…"}</p>
                </div>))}
            </div>
            <p className="mt-3 text-sm text-slate-700">
              {r ? <><strong>{r.full_mocks_available}</strong> full mock{r.full_mocks_available === 1 ? "" : "s"} of never-seen questions ready.</> : "Checking…"}
              {r?.generating && <span className="ml-2 inline-flex items-center gap-1.5 text-teal-700"><HeartPulse className="h-4 w-4 animate-pulse" />Writing and double-checking more…</span>}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              New questions are written by AI and kept only when a second, independent AI gets the same answer. They are
              not yet expert-reviewed, so report anything that looks wrong from your result page.
            </p>
          </div>
        </div>
        <div className="card text-sm">
          <h2 className="h2 mb-2">The real exam</h2>
          <ul className="space-y-1.5 text-slate-700">
            <li><strong>{pattern.total_questions}</strong> questions · <strong>{pattern.duration_minutes / 60} hours</strong>{pattern.exam_time && ` · ${pattern.exam_time}`}</li>
            <li>Marking <strong>+{pattern.marks_correct}</strong> correct · <strong>{pattern.marks_wrong}</strong> wrong · 0 blank</li>
            <li className="flex flex-wrap gap-1">{pattern.sections.map((s) => <SubjectBadge key={s.name} subject={s.name} />)}</li>
          </ul>
          <p className="mt-2 text-xs text-slate-500">{pattern.format_note} {pattern.verify_note}</p>
        </div>
      </section>

      <section>
        <h2 className="h2 mb-2">Choose a test</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(Object.keys(MODE_INFO) as Mode[]).map((m) => {
            const disabled = m === "full" && !fullPossible;
            const Icon = MODE_INFO[m].icon;
            return (
              <button key={m} disabled={disabled} onClick={() => { setMode(m); setPreparing(null); }} aria-pressed={mode === m}
                className={`card card-lift text-left ${mode === m ? "ring-2 ring-teal-600" : ""} ${disabled ? "opacity-50" : ""}`}>
                <span className="mb-2 grid h-9 w-9 place-items-center rounded-xl bg-teal-50 text-teal-700 ring-1 ring-teal-100"><Icon className="h-5 w-5" /></span>
                <p className="font-semibold">{MODE_INFO[m].title}</p>
                <p className="mt-1 text-xs text-slate-600">{disabled ? "Not enough never-seen questions yet." : MODE_INFO[m].text}</p>
              </button>);
          })}
        </div>
      </section>

      {mode && (
        <section className="card space-y-4">
          <h2 className="h2">{MODE_INFO[mode].title}</h2>
          {mode === "mini" && (
            <label className="block text-sm">Questions per section
              <select className="input mt-1 max-w-56" value={perSection} onChange={(e) => setPerSection(Number(e.target.value))}>
                {[5, 10, 15, 20, 30].map((n) => <option key={n} value={n}>{n} ({n * 4} total, {n * 4} min)</option>)}</select></label>)}
          {mode === "subject" && (
            <div className="flex flex-wrap gap-3 text-sm">
              <label>Subject <select className="input mt-1" value={subject} onChange={(e) => setSubject(e.target.value)}>
                {[...SECTIONS, "Biology"].map((s) => <option key={s}>{s}</option>)}</select></label>
              <label>Questions <input className="input mt-1 w-28" type="number" min={5} max={90} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>
            </div>)}
          {mode === "chapter" && syl.data && (
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-2">{SECTIONS.map((s) => {
                const Icon = SUBJECT_STYLE[s].icon;
                return (
                  <button key={s} onClick={() => setChapterSubject(s)} aria-pressed={chapterSubject === s}
                    className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs ring-1 ${chapterSubject === s ? "bg-teal-700 text-white ring-teal-700" : "ring-slate-300"}`}>
                    <Icon className="h-3.5 w-3.5" />{s}</button>);
              })}</div>
              <div className="grid max-h-72 gap-1 overflow-y-auto rounded-lg border border-slate-200 p-2 sm:grid-cols-2">
                {syl.data.chapters.filter((c) => c.subject === chapterSubject).map((c) => (
                  <label key={c.id} className="flex items-center gap-2 rounded px-1 py-0.5">
                    <input type="checkbox" disabled={!chapterIds.includes(c.id) && chapterIds.length >= 10}
                      checked={chapterIds.includes(c.id)}
                      onChange={() => setChapterIds((ids) => ids.includes(c.id) ? ids.filter((x) => x !== c.id) : [...ids, c.id])} />
                    <span>{c.name} <span className="text-xs text-slate-500">(Class {c.class_level})</span></span>
                  </label>))}
              </div>
              <p className="text-xs text-slate-500">{chapterIds.length} selected. If a chapter runs short of new questions, fresh ones are written for it.</p>
              <label>Questions <input className="input mt-1 w-28" type="number" min={5} max={90} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>
            </div>)}
          {mode === "weak" && (
            <label className="block text-sm">Questions <input className="input mt-1 w-28" type="number" min={5} max={90} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>)}

          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} className="mt-1" />
            <span><strong>Strict OMR mode</strong>: like the real answer sheet, once you fill a bubble you cannot change it.</span>
          </label>
          <p className="text-xs text-slate-500">
            Next you&apos;ll get your admit card, the instructions and your OMR sheet. The clock starts only when you break the
            seal on the booklet.
          </p>
          <ErrorBox error={error} />
          {preparing ? (
            <div className="rounded-xl border border-teal-200 bg-teal-50/60 p-4 text-sm text-teal-900" role="status">
              <Loading label="Writing and double-checking fresh questions for your paper…" />
              <p>{preparing.detail}</p>
              <p className="mt-1 text-xs">Keep this page open: your admit card opens automatically when the paper is ready.</p>
            </div>
          ) : (
            <button className="btn" disabled={busy || !!inProgress || (mode === "chapter" && chapterIds.length === 0)} onClick={prepare}>
              {busy ? "Preparing paper…" : "Prepare my paper"}</button>)}
          {inProgress && <p className="text-xs text-slate-500">Finish your current test before starting another.</p>}
        </section>)}

      <section className="card">
        <h2 className="h2 mb-2">Your tests</h2>
        {!attempts.data?.length ? <p className="muted">No tests yet.</p> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="py-1">Test</th><th>Date</th><th>Questions</th><th>Score</th><th /></tr></thead>
            <tbody>{attempts.data.map((a) => (
              <tr key={a.id} className="border-t border-slate-100"><td className="py-1">{a.title}</td><td>{fmtDate(a.started_at)}</td><td>{a.questions}</td>
                <td>{a.status === "submitted" ? `${a.score} / ${a.max_score}` : a.status === "ready" ? "Not started" : "In progress"}</td>
                <td><Link className="text-teal-700 underline" href={`/practice/${a.id}`}>{a.status === "submitted" ? "Review" : a.status === "ready" ? "Open" : "Resume"}</Link></td></tr>))}</tbody>
          </table></div>)}
      </section>

      {perf.data && perf.data.chapters.length > 0 && (
        <section className="card">
          <h2 className="h2 mb-1">Chapter-wise accuracy</h2>
          <p className="muted mb-2 text-xs">{perf.data.note}</p>
          <div className="overflow-x-auto"><table className="w-full min-w-[480px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="py-1">Chapter</th><th>Subject</th><th>Answered</th><th>Accuracy</th><th /></tr></thead>
            <tbody>{perf.data.chapters.slice(0, 15).map((c) => (
              <tr key={c.chapter_id} className="border-t border-slate-100"><td className="py-1">{c.chapter}</td><td><SubjectBadge subject={c.subject} /></td><td>{c.attempted}</td>
                <td className={c.accuracy !== null && c.accuracy < 50 ? "font-medium text-red-700" : ""}>{c.accuracy ?? "—"}{c.accuracy !== null && "%"}</td>
                <td><Link className="text-teal-700 underline" href={`/practice?chapter=${c.chapter_id}`}>Practise</Link></td></tr>))}</tbody>
          </table></div>
        </section>)}
    </div>
  );
}

export default function PracticePage() {
  return <Suspense fallback={<Loading />}><Builder /></Suspense>;
}
