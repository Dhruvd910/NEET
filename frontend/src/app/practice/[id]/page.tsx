"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { RoughPad, ringBell, Stem } from "@/components/exam";
import { Asclepius, Bell, Clipboard, Clock, Expand, Flag, Pencil } from "@/components/icons";
import { ErrorBox, Loading, Notice, SignInPrompt, SubjectBadge, useApi } from "@/components/ui";
import { api, ApiError, type Me } from "@/lib/api";
import { type AttemptView, clock, type QuestionView } from "@/lib/practice";

type Local = { selected: number | null; marked: boolean; visited: boolean };
const OPTION_LABEL = ["1", "2", "3", "4"];

export default function AttemptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [view, setView] = useState<AttemptView | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api<AttemptView>(`/api/exams/attempts/${id}`).then(setView).catch(setError);
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (error) return <SignInPrompt error={error} />;
  if (!view) return <Loading label="Fetching your paper…" />;
  if (view.status === "ready") return <ExamDay view={view} onStarted={setView} />;
  return view.status === "submitted" ? <Result view={view} /> : <ExamRoom view={view} onSubmitted={setView} />;
}

// ---------------------------------------------------------------- exam day: admit card → instructions → OMR particulars

function ExamDay({ view, onStarted }: { view: AttemptView; onStarted: (v: AttemptView) => void }) {
  const me = useApi<Me>("/api/auth/me");
  const profile = useApi<{ profile: { display_name: string | null } | null }>("/api/profile");
  const [step, setStep] = useState(1);
  const [agreed, setAgreed] = useState(false);
  const [roll, setRoll] = useState("");
  const [series, setSeries] = useState<string | null>(null);
  const [num, setNum] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const name = profile.data?.profile?.display_name || me.data?.email || "Candidate";
  const total = view.questions.length || Object.values(view.section_counts).reduce((a, b) => a + b, 0);
  const minutes = Math.round(view.duration_seconds / 60);
  const code = view.booklet_code ?? "Q1";
  const particularsOk = roll === view.roll_number && series === code[0] && num === code[1];

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      // Not awaited: some browsers never settle this promise (e.g. embedded views), and the exam must still start.
      if (fullscreen) document.documentElement.requestFullscreen?.()?.catch(() => undefined);
      const opened = await api<AttemptView>(`/api/exams/attempts/${view.id}/start`, { method: "POST" });
      ringBell(2);
      onStarted(opened);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  const steps = ["Admit card", "Instructions", "OMR particulars"];
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <ol className="flex flex-wrap items-center gap-2 text-xs font-semibold" aria-label="Exam-day steps">
        {steps.map((s, i) => (
          <li key={s} className={`flex items-center gap-2 rounded-full px-3 py-1 ring-1 ${step === i + 1 ? "bg-teal-700 text-white ring-teal-700" : step > i + 1 ? "bg-teal-50 text-teal-800 ring-teal-200" : "bg-white text-slate-500 ring-slate-200"}`}>
            {i + 1}. {s}</li>))}
      </ol>

      {step === 1 && (
        <section className="card relative overflow-hidden" aria-labelledby="admit-title">
          <div aria-hidden="true" className="med-pattern pointer-events-none absolute inset-0 opacity-40" />
          <div className="relative">
            <div className="flex items-center gap-3 border-b border-dashed border-slate-300 pb-3">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-teal-500 to-cyan-600 text-white"><Asclepius className="h-6 w-6" /></span>
              <div>
                <p className="eyebrow text-teal-700">NEET Compass · practice examination</p>
                <h1 id="admit-title" className="h2 !text-xl">Admit card</h1>
              </div>
              <span className="ml-auto rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-200">Practice only · not an official document</span>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_120px]">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-slate-500">Candidate</dt><dd className="font-semibold">{name}</dd>
                <dt className="text-slate-500">Roll number</dt><dd className="font-mono text-base font-bold tracking-wider">{view.roll_number}</dd>
                <dt className="text-slate-500">Paper</dt><dd>{view.title}</dd>
                <dt className="text-slate-500">Questions</dt><dd>{total} · {Object.entries(view.section_counts).map(([s, n]) => `${s} ${n}`).join(" · ")}</dd>
                <dt className="text-slate-500">Duration</dt><dd>{minutes} minutes{view.pattern.exam_time && view.mode === "full" && <> (real exam: {view.pattern.exam_time})</>}</dd>
                <dt className="text-slate-500">Centre</dt><dd>Your study desk</dd>
              </dl>
              <div className="grid h-36 place-items-center rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 text-center text-xs text-slate-500">
                <span><span className="block text-3xl font-bold text-slate-400">{name.slice(0, 1).toUpperCase()}</span>Photograph</span>
              </div>
            </div>
            <div className="mt-4 rounded-lg bg-teal-50/70 p-3 text-xs text-teal-950 ring-1 ring-teal-100">
              <p className="font-semibold">Exam-day habits to practise</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                <li>Sit at a clear desk with only a pen and blank paper, at the same time of day as the real exam.</li>
                <li>On the real day, follow the reporting time, dress code and permitted items printed on your NTA admit card.</li>
              </ul>
            </div>
            <button className="btn mt-4" onClick={() => setStep(2)}>Continue to instructions</button>
          </div>
        </section>)}

      {step === 2 && (
        <section className="card booklet space-y-3" aria-labelledby="instr-title">
          <h1 id="instr-title" className="text-center text-lg font-bold uppercase tracking-wide">Important instructions to candidates</h1>
          <ol className="list-decimal space-y-2 pl-5 text-[15px] leading-relaxed">
            <li>This test booklet has <strong>{total}</strong> questions ({Object.entries(view.section_counts).map(([s, n]) => `${s} ${n}`).join(", ")}). Each question has four options, of which only one is correct.</li>
            <li>Each correct answer earns <strong>{view.pattern.marks_correct} marks</strong>. For each incorrect answer, <strong>{Math.abs(view.pattern.marks_wrong)} mark</strong> is deducted. Unanswered questions get no marks.</li>
            <li>You have <strong>{minutes} minutes</strong>. Bells and announcements will mark 30, 10 and 5 minutes remaining. When time is up the answer sheet is collected automatically.</li>
            <li>Mark your answer by completely darkening one bubble for each question on the OMR answer sheet. {view.strict_omr
              ? <strong>Strict OMR mode is on: a darkened bubble cannot be changed or erased, just like ball-point pen on the real sheet.</strong>
              : "In the real exam answers cannot be changed; in this practice you may change them."}</li>
            <li>Do your rough work only on the rough-work sheet, never on the OMR answer sheet.</li>
            <li>Calculators, phones and other electronic devices are not allowed. Leaving the exam window is recorded in your result.</li>
            <li>Check that the Test Booklet Code printed on the booklet matches the code you darken on the OMR sheet.</li>
          </ol>
          <label className="flex items-start gap-2 font-sans text-sm">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-1" />
            I have read and understood the instructions.
          </label>
          <div className="flex gap-2 font-sans">
            <button className="btn-secondary" onClick={() => setStep(1)}>Back</button>
            <button className="btn" disabled={!agreed} onClick={() => setStep(3)}>I agree · Fill OMR particulars</button>
          </div>
        </section>)}

      {step === 3 && (
        <section className="card space-y-4" aria-labelledby="omr-title">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 id="omr-title" className="h2">Fill in your OMR particulars</h1>
            <div className="rounded-lg border-2 border-slate-800 px-3 py-1.5 text-center font-mono">
              <p className="text-[10px] font-sans uppercase tracking-wider text-slate-500">Sealed booklet · Test Booklet Code</p>
              <p className="text-xl font-bold tracking-widest">{code}</p>
            </div>
          </div>
          <p className="muted">Copy your roll number from the admit card and darken the booklet code exactly as printed on the booklet. Mistakes here cost marks in the real exam.</p>
          <div className="grid gap-4 rounded-xl border-2 border-rose-200 bg-rose-50/40 p-4 sm:grid-cols-2">
            <label className="block text-sm font-semibold text-rose-900">Roll number
              <input className="input mt-1 font-mono tracking-widest" inputMode="numeric" maxLength={10} value={roll}
                onChange={(e) => setRoll(e.target.value.replace(/\D/g, ""))} placeholder="10 digits" aria-describedby="roll-hint" />
              <span id="roll-hint" className="mt-1 block text-xs font-normal text-rose-800/80">On your admit card: {view.roll_number}</span>
            </label>
            <div className="text-sm font-semibold text-rose-900">
              <p>Test Booklet Code</p>
              <div className="mt-2 flex gap-4">
                <div role="radiogroup" aria-label="Booklet series" className="flex gap-1.5">
                  {["Q", "R", "S"].map((l) => (
                    <button key={l} type="button" role="radio" aria-checked={series === l} onClick={() => setSeries(l)}
                      className={`h-8 w-8 rounded-full border-2 font-mono text-sm ${series === l ? "border-slate-900 bg-slate-900 text-white" : "border-rose-300 bg-white text-rose-900"}`}>{l}</button>))}
                </div>
                <div role="radiogroup" aria-label="Booklet number" className="flex gap-1.5">
                  {["1", "2", "3", "4"].map((d) => (
                    <button key={d} type="button" role="radio" aria-checked={num === d} onClick={() => setNum(d)}
                      className={`h-8 w-8 rounded-full border-2 font-mono text-sm ${num === d ? "border-slate-900 bg-slate-900 text-white" : "border-rose-300 bg-white text-rose-900"}`}>{d}</button>))}
                </div>
              </div>
            </div>
          </div>
          {roll.length === 10 && roll !== view.roll_number && <p className="text-sm text-red-700" role="alert">That roll number doesn&apos;t match your admit card.</p>}
          {series && num && `${series}${num}` !== code && <p className="text-sm text-red-700" role="alert">The code you darkened doesn&apos;t match the booklet ({code}).</p>}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={fullscreen} onChange={(e) => setFullscreen(e.target.checked)} />
            Use full screen during the exam (recommended)
          </label>
          <ErrorBox error={error} />
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={() => setStep(2)}>Back</button>
            <button className="btn" disabled={!particularsOk || busy} onClick={begin}>
              <Clipboard className="h-4 w-4" />{busy ? "Opening…" : "Break the seal and begin"}</button>
          </div>
        </section>)}
    </div>
  );
}

// ---------------------------------------------------------------- exam room

const ANNOUNCEMENTS: Record<number, string> = {
  1800: "Invigilator: 30 minutes remaining.",
  600: "Invigilator: 10 minutes remaining. Check your OMR sheet.",
  300: "Invigilator: 5 minutes remaining. Make sure every answer is darkened on the OMR sheet.",
};

function ExamRoom({ view, onSubmitted }: { view: AttemptView; onSubmitted: (v: AttemptView) => void }) {
  const qs = view.questions;
  const [answers, setAnswers] = useState<Local[]>(() => qs.map((q) => ({ selected: q.selected_index, marked: q.marked_for_review, visited: q.visited })));
  const [cur, setCur] = useState(() => Math.max(0, qs.findIndex((q) => !q.visited)));
  const [remaining, setRemaining] = useState(view.remaining_seconds);
  const [message, setMessage] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>("The exam has begun. All the best, future doctor!");
  const [confirming, setConfirming] = useState(false);
  const [showSheet, setShowSheet] = useState(false);
  const [rough, setRough] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const enteredAt = useRef(Date.now());
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const answersRef = useRef(answers);
  answersRef.current = answers;

  const submit = useCallback(async (auto = false) => {
    setSubmitting(true);
    await chain.current.catch(() => undefined);
    try {
      const done = await api<AttemptView>(`/api/exams/attempts/${view.id}/submit`, { method: "POST" });
      if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
      if (auto) ringBell(3);
      onSubmitted(done);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not submit. Check your connection and try again.");
      setSubmitting(false);
    }
    window.scrollTo(0, 0);
  }, [onSubmitted, view.id]);

  /** Save one question's state. Requests are chained so they reach the server in order. */
  const persist = useCallback((index: number, state: Local, withTime: boolean) => {
    const delta = withTime ? Math.round((Date.now() - enteredAt.current) / 1000) : 0;
    if (withTime) enteredAt.current = Date.now();
    chain.current = chain.current.then(() => api<{ remaining_seconds: number }>(
      `/api/exams/attempts/${view.id}/answers/${qs[index].position}`,
      { method: "PUT", json: { selected_index: state.selected, marked_for_review: state.marked, time_spent_delta: Math.min(delta, 3600) } },
    ).then((r) => setRemaining(r.remaining_seconds)).catch((e) => {
      if (e instanceof ApiError && e.message.startsWith("Time is up")) { submit(true); return; }
      if (e instanceof ApiError && e.message.startsWith("Strict OMR")) {
        setMessage(e.message);
        return;
      }
      setMessage("Answer not saved — check your connection. It will be retried when you move on.");
    }));
  }, [qs, submit, view.id]);

  const update = (index: number, patch: Partial<Local>) => {
    const next = { ...answersRef.current[index], ...patch, visited: true };
    setAnswers((a) => a.map((x, i) => (i === index ? next : x)));
    persist(index, next, index === cur);
  };

  const go = (index: number) => {
    if (index < 0 || index >= qs.length || index === cur) return;
    persist(cur, answersRef.current[cur], true);
    setAnswers((a) => a.map((x, i) => (i === index ? { ...x, visited: true } : x)));
    setCur(index);
    setMessage(null);
  };

  const choose = (index: number, option: number) => {
    const a = answersRef.current[index];
    if (view.strict_omr && a.selected !== null) {
      if (a.selected !== option) setMessage("Strict OMR mode: a filled bubble cannot be changed, just like the real answer sheet.");
      return;
    }
    if (index !== cur) go(index);
    update(index, { selected: option });
  };

  // Countdown; the server is the real clock and auto-submits late attempts too.
  useEffect(() => {
    const t = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (remaining === 0 && !submitting) {
      setAnnouncement("Time is up. Pens down — your answer sheet is being collected.");
      submit(true);
    }
    if (ANNOUNCEMENTS[remaining] && remaining < view.duration_seconds) {
      setAnnouncement(ANNOUNCEMENTS[remaining]);
      ringBell(1);
    }
  }, [remaining, submit, submitting, view.duration_seconds]);
  useEffect(() => {
    if (!announcement) return;
    const t = setTimeout(() => setAnnouncement(null), 8000);
    return () => clearTimeout(t);
  }, [announcement]);

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        api(`/api/exams/attempts/${view.id}/focus-lost`, { method: "POST" }).catch(() => undefined);
        setMessage("You left the exam window. This is noted in your result.");
      }
    };
    const onUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [view.id]);

  const q = qs[cur];
  const a = answers[cur];
  const sections = Array.from(new Set(qs.map((x) => x.section)));
  const answered = answers.filter((x) => x.selected !== null).length;
  const marked = answers.filter((x) => x.marked).length;
  const low = remaining <= 300;
  const firstOfSection = cur === 0 || qs[cur - 1].section !== q.section;

  return (
    <div className={`space-y-3 ${rough ? "pb-[42vh]" : ""}`}>
      <div className="sticky top-14 z-20 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold">{view.title}</h1>
          <p className="font-mono text-[11px] text-slate-500">Booklet {view.booklet_code} · Roll {view.roll_number}</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 font-mono text-lg tabular-nums ${low ? "animate-pulse bg-red-100 text-red-800" : "bg-slate-100 text-slate-900"}`}
          role="timer" aria-label="Time left"><Clock className="h-4 w-4" />{clock(remaining)}</span>
        <button className="btn-ghost !px-2" onClick={() => setRough(!rough)} aria-pressed={rough} title="Rough work"><Pencil className="h-4 w-4" /><span className="hidden sm:inline">Rough work</span></button>
        <button className="btn-ghost !px-2" title="Full screen" aria-label="Full screen"
          onClick={() => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.())?.catch?.(() => undefined)}>
          <Expand className="h-4 w-4" /></button>
        <button className="btn" onClick={() => setConfirming(true)} disabled={submitting}>Submit</button>
      </div>

      {announcement && (
        <div role="status" className="flex items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-900">
          <Bell className="h-4 w-4 shrink-0" />{announcement}
        </div>)}

      <div role="tablist" aria-label="Sections" className="flex gap-1 overflow-x-auto">
        {sections.map((s) => {
          const idx = qs.map((x, i) => [x, i] as const).filter(([x]) => x.section === s);
          const done = idx.filter(([, i]) => answers[i].selected !== null).length;
          return (
            <button key={s} role="tab" aria-selected={q.section === s} onClick={() => go(idx[0][1])}
              className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm ${q.section === s ? "bg-teal-700 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200"}`}>
              {s} <span className="text-xs opacity-80">{done}/{idx.length}</span></button>);
        })}
      </div>

      {message && <Notice tone="warn">{message}</Notice>}

      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <article className="booklet relative rounded-2xl border border-slate-300 p-5 shadow-sm sm:p-7" aria-labelledby="qnum">
          <div aria-hidden="true" className="absolute right-4 top-3 font-mono text-[10px] text-slate-400">{view.booklet_code}</div>
          {firstOfSection && (
            <div className="mb-4 flex items-center gap-2 border-b-2 border-double border-slate-400 pb-2">
              <SubjectBadge subject={q.section} />
              <p className="text-sm font-bold uppercase tracking-[0.2em] text-slate-700">{q.section}</p>
            </div>)}
          <div className="flex gap-3 text-[17px] leading-relaxed text-slate-900">
            <p id="qnum" className="shrink-0 font-bold">{q.position}.</p>
            <div className="min-w-0 flex-1 space-y-4">
              <Stem text={q.stem} />
              <ol className="space-y-2">
                {q.options.map((opt, i) => {
                  const sel = a.selected === i;
                  return (
                    <li key={i}>
                      <button onClick={() => choose(cur, i)} aria-pressed={sel}
                        className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition ${sel ? "bg-slate-900/5 font-semibold ring-1 ring-slate-900" : "hover:bg-slate-900/[0.03]"}`}>
                        {/* As printed in the booklet; the bubbles live on the OMR sheet. */}
                        <span className="shrink-0">({OPTION_LABEL[i]})</span>
                        <span>{opt}</span>
                      </button>
                    </li>);
                })}
              </ol>
            </div>
          </div>
          <div className="mt-6 flex flex-wrap gap-2 font-sans">
            <button className="btn-secondary" onClick={() => go(cur - 1)} disabled={cur === 0}>← Previous</button>
            <button className="btn-secondary" onClick={() => update(cur, { marked: !a.marked })}><Flag className="h-4 w-4" />{a.marked ? "Unmark" : "Mark for review"}</button>
            {!view.strict_omr && <button className="btn-secondary" onClick={() => update(cur, { selected: null })} disabled={a.selected === null}>Clear</button>}
            <button className="btn" onClick={() => go(cur + 1)} disabled={cur === qs.length - 1}>Save & next →</button>
          </div>
        </article>

        <aside className="h-fit rounded-2xl border-2 border-rose-200 bg-rose-50/40 p-4 lg:sticky lg:top-32">
          <button className="mb-1 flex w-full items-center justify-between text-left font-semibold text-rose-900 lg:pointer-events-none" onClick={() => setShowSheet(!showSheet)}
            aria-expanded={showSheet}>
            OMR answer sheet <span className="text-xs font-normal text-rose-800 lg:hidden">{showSheet ? "Hide" : "Show"}</span></button>
          <p className="mb-2 font-mono text-[11px] text-rose-900/80">Roll {view.roll_number} · Code {view.booklet_code}</p>
          <p className="mb-2 text-xs text-rose-900/80">{answered} answered · {qs.length - answered} blank · {marked} marked</p>
          <div className={`${showSheet ? "" : "hidden"} max-h-[60vh] overflow-y-auto lg:block`}>
            <OmrSheet questions={qs} answers={answers} current={cur} onGo={go} onChoose={choose} />
          </div>
        </aside>
      </div>

      {rough && <RoughPad onClose={() => setRough(false)} />}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="card max-w-sm space-y-3">
            <h2 id="confirm-title" className="h2">Hand in your answer sheet?</h2>
            <p className="text-sm">{answered} answered, {qs.length - answered} left blank{marked ? `, ${marked} marked for review` : ""}. You have {clock(remaining)} left.</p>
            <p className="text-sm text-slate-600">You cannot change answers after submitting.</p>
            <div className="flex gap-2">
              <button className="btn" onClick={() => { persist(cur, answersRef.current[cur], true); submit(); }} disabled={submitting}>
                {submitting ? "Submitting…" : "Yes, submit"}</button>
              <button className="btn-secondary" onClick={() => setConfirming(false)}>Keep working</button>
            </div>
          </div>
        </div>)}
    </div>
  );
}

function OmrSheet({ questions, answers, current, onGo, onChoose }: { questions: QuestionView[]; answers: Local[]; current: number;
  onGo: (i: number) => void; onChoose: (i: number, opt: number) => void }) {
  let lastSection = "";
  return (
    <div className="space-y-0.5 font-mono text-xs">
      {questions.map((q, i) => {
        const header = q.section !== lastSection ? (lastSection = q.section) : null;
        const a = answers[i];
        return (
          <div key={q.position}>
            {header && <p className="mt-2 mb-1 font-sans text-xs font-semibold uppercase tracking-wider text-rose-900">{header}</p>}
            <div className={`flex items-center gap-1.5 rounded px-1 ${i === current ? "bg-white ring-1 ring-rose-300" : ""}`}>
              <button className="w-8 text-right tabular-nums text-rose-950" onClick={() => onGo(i)} aria-label={`Go to question ${q.position}`}>
                {q.position}{a.marked && <span className="text-amber-600" title="Marked for review">*</span>}</button>
              {[0, 1, 2, 3].map((o) => (
                <button key={o} onClick={() => onChoose(i, o)} aria-label={`Question ${q.position}, option ${o + 1}`} aria-pressed={a.selected === o}
                  className={`h-5 w-5 rounded-full border text-[10px] leading-none ${a.selected === o ? "border-slate-900 bg-slate-900 text-white" : "border-rose-300 bg-white text-rose-400 hover:border-rose-600"}`}>
                  {o + 1}</button>))}
            </div>
          </div>);
      })}
    </div>
  );
}

// ---------------------------------------------------------------- result

const OUTCOME_STYLE = { correct: "text-emerald-700", wrong: "text-red-700", skipped: "text-slate-500" } as const;
const REPORT_REASONS = [["wrong_answer", "The answer key is wrong"], ["unclear", "Unclear or two options correct"],
  ["out_of_syllabus", "Not in the NEET syllabus"], ["typo", "Typo or formatting"], ["other", "Something else"]] as const;

function ReportButton({ attemptId, position }: { attemptId: number; position: number }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string>("wrong_answer");
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "sent" | "error">("idle");
  if (state === "sent") return <p className="text-xs text-emerald-700">Thanks — reported. Questions with several reports are hidden until checked.</p>;
  if (!open) return <button className="text-xs text-slate-500 underline hover:text-slate-800" onClick={() => setOpen(true)}>Report a problem</button>;
  return (
    <form className="flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 p-2 text-xs" onSubmit={async (e) => {
      e.preventDefault();
      try {
        await api(`/api/exams/attempts/${attemptId}/report/${position}`, { method: "POST", json: { reason, note: note || null } });
        setState("sent");
      } catch { setState("error"); }
    }}>
      <select className="input !w-auto !py-1 text-xs" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Problem">
        {REPORT_REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      <input className="input !w-56 !py-1 text-xs" maxLength={1000} placeholder="What's wrong? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="btn-secondary !py-1 text-xs">Send</button>
      <button type="button" className="btn-ghost !py-1 text-xs" onClick={() => setOpen(false)}>Cancel</button>
      {state === "error" && <span className="text-red-700">Couldn&apos;t send. Try again.</span>}
    </form>
  );
}

function Result({ view }: { view: AttemptView }) {
  const r = view.result!;
  const [filter, setFilter] = useState<"all" | "wrong" | "skipped" | "correct" | "marked">("wrong");
  const shown = view.questions.filter((q) => filter === "all" || (filter === "marked" ? q.marked_for_review : q.outcome === filter));
  const mins = Math.round(r.time_used_seconds / 60);
  const pct = Math.max(0, Math.round((100 * r.score) / r.max_score));

  return (
    <div className="space-y-5">
      <section className="card relative overflow-hidden">
        <div aria-hidden="true" className="med-pattern pointer-events-none absolute inset-0 opacity-40 [mask-image:linear-gradient(to_left,black,transparent_65%)]" />
        <div className="relative flex flex-wrap items-center gap-5">
          <div className="grid h-28 w-28 shrink-0 place-items-center rounded-full"
            style={{ background: `conic-gradient(#0d9488 ${pct * 3.6}deg, #e2e8f0 0)` }}>
            <div className="grid h-[5.6rem] w-[5.6rem] place-items-center rounded-full bg-white text-center">
              <p className="text-2xl font-extrabold leading-none tabular-nums">{r.score}</p>
              <p className="text-[11px] text-slate-500">of {r.max_score}</p>
            </div>
          </div>
          <div className="min-w-0">
            <p className="eyebrow text-teal-700">Scorecard</p>
            <h1 className="h1 !text-2xl sm:!text-3xl">{view.title}</h1>
            <p className="muted">Practice score only — not a prediction of your NEET score or rank. Booklet {view.booklet_code} · Roll {view.roll_number}</p>
          </div>
        </div>
      </section>
      {r.auto_submitted && <Notice tone="warn">Time ran out, so your answer sheet was collected automatically with the answers saved so far.</Notice>}
      {(view.has_sample_questions || view.has_ai_questions) && (
        <Notice>This paper used practice questions that are not yet expert-reviewed{view.has_ai_questions ? " (AI-written; each answer was confirmed by a second, independent AI)" : ""}. If something looks wrong, use “Report a problem” below.</Notice>)}

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[["Correct", r.correct, "text-emerald-700"], ["Wrong", `${r.wrong} (−${r.negative_marks})`, "text-red-700"],
          ["Left blank", r.skipped, "text-slate-700"], ["Accuracy", r.accuracy === null ? "—" : `${r.accuracy}%`, "text-slate-900"],
          ["Time used", `${mins} / ${Math.round(view.duration_seconds / 60)} min`, "text-slate-900"]].map(([k, v, c]) => (
          <div key={k as string} className="card"><p className="muted">{k}</p><p className={`text-xl font-semibold ${c}`}>{v}</p></div>))}
      </section>
      <p className="text-sm text-slate-600">
        {r.focus_lost_count > 0 && `Left the exam window ${r.focus_lost_count} time(s). `}
        {r.recorded_as_mock_test && <>Added to your <Link className="underline" href="/mock-tests">mock-test trend</Link>.</>}
      </p>

      {r.advice.length > 0 && (
        <section className="card"><h2 className="h2 mb-2">Doctor&apos;s notes: what to work on</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm">{r.advice.map((t) => <li key={t}>{t}</li>)}</ul></section>)}

      <section className="card overflow-x-auto">
        <h2 className="h2 mb-2">By section</h2>
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="text-xs text-slate-500"><tr><th className="py-1">Section</th><th>Score</th><th>Correct</th><th>Wrong</th><th>Blank</th><th>Accuracy</th><th>Avg time / Q</th></tr></thead>
          <tbody>{r.sections.map((s) => (
            <tr key={s.section} className="border-t border-slate-100"><td className="py-1.5"><SubjectBadge subject={s.section} /></td><td>{s.score} / {s.max}</td><td>{s.correct}</td>
              <td>{s.wrong}</td><td>{s.questions - s.attempted}</td><td>{s.accuracy ?? "—"}{s.accuracy !== null && "%"}</td><td>{s.avg_seconds}s</td></tr>))}</tbody>
        </table>
      </section>

      <section className="card overflow-x-auto">
        <h2 className="h2 mb-2">By chapter (weakest first)</h2>
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead className="text-xs text-slate-500"><tr><th className="py-1">Chapter</th><th>Subject</th><th>Correct</th><th>Accuracy</th><th /></tr></thead>
          <tbody>{r.chapters.map((c) => (
            <tr key={c.chapter_id} className="border-t border-slate-100"><td className="py-1">{c.chapter}</td><td><SubjectBadge subject={c.subject} /></td>
              <td>{c.correct} / {c.questions}</td><td className={c.accuracy !== null && c.accuracy < 50 ? "font-medium text-red-700" : ""}>{c.accuracy ?? "—"}{c.accuracy !== null && "%"}</td>
              <td><Link className="text-teal-700 underline" href={`/practice?chapter=${c.chapter_id}`}>Practise</Link></td></tr>))}</tbody>
        </table>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="h2 mr-2">Review answers</h2>
          {(["wrong", "skipped", "marked", "correct", "all"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
              className={`rounded-full px-3 py-1 text-xs capitalize ring-1 ${filter === f ? "bg-teal-700 text-white ring-teal-700" : "ring-slate-300"}`}>{f}</button>))}
        </div>
        {shown.length === 0 && <p className="muted">Nothing here.</p>}
        {shown.map((q) => (
          <article key={q.position} className="booklet space-y-2 rounded-2xl border border-slate-300 p-4 text-[15px]">
            <p className="font-sans text-xs text-slate-500">
              Q{q.position} · {q.section} · {q.chapter}{q.topic && ` · ${q.topic}`}{q.difficulty && ` · ${q.difficulty}`}
              {q.time_spent_seconds !== undefined && ` · ${q.time_spent_seconds}s`} ·{" "}
              <span className={`font-medium ${OUTCOME_STYLE[q.outcome!]}`}>{q.outcome}</span>
            </p>
            <Stem text={q.stem} />
            <ol className="space-y-1">{q.options.map((o, i) => (
              <li key={i} className={`rounded px-2 py-1 ${i === q.correct_index ? "bg-emerald-50 text-emerald-900" : i === q.selected_index ? "bg-red-50 text-red-900" : ""}`}>
                ({i + 1}) {o}{i === q.correct_index && " ✓ correct"}{i === q.selected_index && i !== q.correct_index && " ✗ your answer"}
                {i === q.selected_index && i === q.correct_index && " (your answer)"}</li>))}</ol>
            {q.explanation && <p className="rounded bg-slate-50 p-2 font-sans text-sm text-slate-700"><strong>Explanation:</strong> {q.explanation}</p>}
            <div className="font-sans"><ReportButton attemptId={view.id} position={q.position} /></div>
          </article>))}
      </section>
      <div className="flex gap-2"><Link className="btn" href="/practice">Take another test</Link><Link className="btn-secondary" href="/study-plan">Study plan</Link></div>
    </div>
  );
}
