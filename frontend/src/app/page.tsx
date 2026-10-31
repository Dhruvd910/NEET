/* eslint-disable @next/next/no-img-element -- animated mascot WebPs are served as-is */
import Link from "next/link";
import {
  Arrow,
  Atom,
  BadgeId,
  Calendar,
  Check,
  Clipboard,
  CompassCross,
  Dna,
  Flask,
  HeartPulse,
  Hospital,
  Leaf,
  Microscope,
  Pill,
  PulseRule,
  Scale,
  Sparkle,
  Stethoscope,
  Target,
  type Icon,
} from "@/components/icons";

type Feature = {
  title: string;
  body: string;
  href: string;
  icon: Icon;
  tint: string;
};

const FEATURES: Feature[] = [
  {
    title: "College predictor",
    body: "Check your rank against past closing ranks — the same way a doctor compares a reading against a normal range.",
    href: "/predictor",
    icon: Stethoscope,
    tint: "from-teal-500 to-emerald-600",
  },
  {
    title: "College profiles",
    body: "Fees, hostels, clinical exposure and cutoffs, each with its source and the date it was checked.",
    href: "/colleges",
    icon: Hospital,
    tint: "from-sky-500 to-blue-600",
  },
  {
    title: "Compare & cost",
    body: "Put 2–5 colleges side by side and estimate the full cost of the course.",
    href: "/compare",
    icon: Scale,
    tint: "from-amber-500 to-orange-600",
  },
  {
    title: "Practice tests",
    body: "NEET-format mocks on an OMR sheet, with section-wise and chapter-wise analysis afterwards.",
    href: "/practice",
    icon: Clipboard,
    tint: "from-violet-500 to-purple-600",
  },
  {
    title: "Study plan",
    body: "A week-by-week plan built from your class, your hours and how far through the syllabus you are.",
    href: "/study-plan",
    icon: Calendar,
    tint: "from-rose-500 to-pink-600",
  },
  {
    title: "Mock-test tracker",
    body: "Log your tests, watch the vitals of your preparation — weak subjects, weak chapters, trend.",
    href: "/mock-tests",
    icon: HeartPulse,
    tint: "from-emerald-500 to-teal-600",
  },
  {
    title: "Counselling help",
    body: "AIQ vs state quota, rounds, documents and a draft preference list you control.",
    href: "/counselling",
    icon: BadgeId,
    tint: "from-cyan-500 to-teal-600",
  },
  {
    title: "Ask the assistant",
    body: "Questions in plain language, answered from our database and official documents — text or voice.",
    href: "/assistant",
    icon: Sparkle,
    tint: "from-fuchsia-500 to-purple-600",
  },
];

const SUBJECTS = [
  { name: "Physics", icon: Atom, tint: "from-sky-500 to-blue-600" },
  { name: "Chemistry", icon: Flask, tint: "from-amber-500 to-orange-600" },
  { name: "Botany", icon: Leaf, tint: "from-emerald-500 to-teal-600" },
  { name: "Zoology", icon: Dna, tint: "from-violet-500 to-purple-600" },
];

const STEPS = [
  ["Create your profile", "Tell us your class, category and rank — or an estimated range. Nothing is public.", "from-teal-500 to-emerald-600"],
  ["Shortlist with evidence", "Predict, compare and cost out colleges, then save a preference order you can change any time.", "from-sky-500 to-indigo-600"],
  ["Practice, then adjust", "Take mocks, find weak chapters and let the weekly plan shift time towards them.", "from-violet-500 to-fuchsia-600"],
];

const TRUST = [
  ["Official sources only", "Facts come from NTA, NMC, MCC, state authorities and college prospectuses — never from an AI’s memory."],
  ["Labels, not promises", "Predictions compare your rank with historical closing ranks. No probabilities, no guarantees."],
  ["Estimates stay marked", "An estimated rank or mock score is always flagged as an estimate, everywhere it appears."],
  ["Your data, your call", "Category is private and used only where counselling rules require it. Export or delete any time."],
];

export default function Home() {
  return (
    <div className="space-y-14">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-[2rem] bg-[#032b2a] px-6 py-10 text-white shadow-2xl shadow-teal-900/25 sm:px-10 sm:py-14 lg:px-14">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <div className="absolute -left-24 -top-32 h-96 w-96 rounded-full bg-teal-400/25 blur-3xl" />
          <div className="absolute -right-16 top-4 h-80 w-80 rounded-full bg-indigo-500/30 blur-3xl" />
          <div className="absolute bottom-[-6rem] left-1/3 h-64 w-64 rounded-full bg-emerald-400/20 blur-3xl" />
          <div className="med-crosses absolute inset-0 opacity-[0.07] [mask-image:radial-gradient(ellipse_at_35%_35%,black,transparent_72%)]" />
        </div>

        <div className="relative grid items-center gap-10 lg:grid-cols-[1fr_0.95fr]">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-teal-50 backdrop-blur sm:text-xs sm:tracking-[0.14em]">
              <CompassCross className="h-3.5 w-3.5 text-emerald-300" />
              NEET-UG → MBBS / BDS
            </span>

            <h1 className="mt-5 max-w-2xl font-display text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl">
              Your NEET journey,{" "}
              <span className="bg-gradient-to-r from-teal-200 via-emerald-200 to-sky-200 bg-clip-text text-transparent">
                mapped out
              </span>
              .
            </h1>

            <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-teal-50/90 sm:text-base">
              Built for future doctors: cutoffs, colleges, costs and a study plan that adapts to you. Every number shows
              where it came from and when it was last checked.
            </p>

            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Link
                href="/register"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-bold text-teal-900 shadow-lg shadow-black/20 transition hover:-translate-y-0.5 hover:bg-teal-50 sm:w-auto"
              >
                Create your profile
                <Arrow className="h-4 w-4" />
              </Link>
              <Link
                href="/predictor"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/25 bg-white/5 px-5 py-3 text-sm font-bold text-white backdrop-blur transition hover:-translate-y-0.5 hover:bg-white/15 sm:w-auto"
              >
                Try the predictor
              </Link>
            </div>

            <ul className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-xs font-semibold text-teal-100/90">
              {["No probability guesses", "Guardian consent built in", "Export or delete any time"].map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <Check className="h-3.5 w-3.5 text-emerald-300" />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          <div className="relative hidden lg:block">
            <div
              aria-hidden="true"
              className="absolute left-1/2 top-1/2 h-48 w-48 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-br from-teal-400/30 to-indigo-500/30 blur-2xl xl:h-60 xl:w-60"
            />
            <div className="relative mx-auto w-fit">
              <img
                src="/mascot/idle-still.png"
                alt="NEET Compass assistant mascot"
                className="animate-float block h-52 w-auto drop-shadow-2xl xl:h-64"
                draggable={false}
              />
              <div className="animate-float absolute right-[94%] top-[10%] w-max rounded-2xl border border-white/25 bg-white/95 px-3 py-2 text-slate-900 shadow-xl shadow-black/25 xl:px-3.5 xl:py-2.5">
                <p className="flex items-center gap-1.5 text-[8.5px] font-bold uppercase tracking-[0.12em] text-slate-500 xl:text-[9.5px]">
                  <Clipboard className="h-3 w-3 text-violet-600" /> Mock format
                </p>
                <p className="font-display text-[12px] font-extrabold whitespace-nowrap xl:text-sm">+4 / −1 / 0</p>
              </div>
              <div className="animate-float absolute bottom-[8%] left-[90%] w-max rounded-2xl border border-white/25 bg-white/95 px-3 py-2 text-slate-900 shadow-xl shadow-black/25 [animation-delay:-2.5s] xl:px-3.5 xl:py-2.5">
                <p className="flex items-center gap-1.5 text-[8.5px] font-bold uppercase tracking-[0.12em] text-slate-500 xl:text-[9.5px]">
                  <HeartPulse className="h-3 w-3 text-rose-500" /> Cutoff history
                </p>
                <p className="font-display text-[12px] font-extrabold whitespace-nowrap xl:text-sm">3 years, per seat type</p>
              </div>
            </div>
          </div>
        </div>

        <dl className="relative mt-10 grid gap-px overflow-hidden rounded-2xl border border-white/15 bg-white/10 sm:grid-cols-3">
          {[
            ["3 yrs", "cutoff history behind every match"],
            ["180 Q · 180 min", "real NEET-format mock tests"],
            ["100%", "facts with a source and last-checked date"],
          ].map(([big, small]) => (
            <div key={big} className="bg-[#032b2a]/40 px-5 py-4 backdrop-blur">
              <dt className="font-display text-xl font-extrabold text-white">{big}</dt>
              <dd className="mt-0.5 text-xs text-teal-100/80">{small}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Features */}
      <section aria-labelledby="features">
        <div className="mb-6">
          <p className="eyebrow flex items-center gap-2 text-teal-700">
            <PulseRule className="h-3 w-8" /> Everything in one place
          </p>
          <h2 id="features" className="h1 mt-1">Pick a tool, get moving</h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => {
            const IconCmp = f.icon;
            return (
              <Link key={f.href} href={f.href} className="card card-lift group relative overflow-hidden">
                <span
                  aria-hidden="true"
                  className={`absolute -right-10 -top-12 h-28 w-28 rounded-full bg-gradient-to-br ${f.tint} opacity-10 blur-2xl transition group-hover:opacity-25`}
                />
                <span className={`relative grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br ${f.tint} text-white shadow-lg shadow-slate-900/15`}>
                  <IconCmp className="h-5 w-5" />
                </span>
                <h3 className="mt-4 font-display text-[15px] font-bold tracking-tight text-slate-900">{f.title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">{f.body}</p>
                <span className="mt-3 inline-flex items-center gap-1 text-[13px] font-bold text-teal-700">
                  Open
                  <Arrow className="h-3.5 w-3.5 transition group-hover:translate-x-1" />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Medical identity band */}
      <section className="relative overflow-hidden rounded-[1.75rem] bg-gradient-to-r from-emerald-700 via-teal-700 to-cyan-800 px-6 py-8 text-white shadow-xl shadow-teal-900/20 sm:px-10">
        <div aria-hidden="true" className="med-crosses absolute inset-0 opacity-[0.08]" />
        <div className="relative flex flex-wrap items-center gap-6">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-white/15 ring-1 ring-white/30 backdrop-blur">
            <Stethoscope className="h-7 w-7" />
          </span>
          <div className="min-w-[16rem] flex-1">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-emerald-100/90">Built for future doctors</p>
            <h2 className="mt-1 font-display text-2xl font-extrabold tracking-tight">From your first mock to your first stethoscope.</h2>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-teal-50/90">
              One honest workspace for the years between a NEET-UG rank and a white coat — cutoffs, counselling, practice
              and planning in the same place.
            </p>
          </div>
          <div className="ml-auto hidden items-center gap-2 text-white/60 sm:flex">
            {[Microscope, Dna, Pill, HeartPulse].map((Ic, i) => (
              <span key={i} className="grid h-10 w-10 place-items-center rounded-xl bg-white/10 ring-1 ring-white/20">
                <Ic className="h-5 w-5" />
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Steps */}
      <section aria-labelledby="how">
        <p className="eyebrow flex items-center gap-2 text-indigo-600">
          <PulseRule className="h-3 w-8" /> How it fits together
        </p>
        <h2 id="how" className="h1 mt-1">From rank to shortlist in three steps</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {STEPS.map(([title, body, tint], i) => (
            <div key={title} className="card card-lift relative">
              <div className={`grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br ${tint} font-display text-sm font-extrabold text-white shadow-lg shadow-slate-900/15`}>
                {i + 1}
              </div>
              <h3 className="mt-4 font-display text-base font-bold text-slate-900">{title}</h3>
              <p className="muted mt-1.5">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Practice + plan showcase */}
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card relative overflow-hidden">
          <p className="eyebrow text-violet-600">Exam room</p>
          <h2 className="mt-1 font-display text-xl font-extrabold tracking-tight text-slate-900">
            180 questions. 180 minutes. Real marking.
          </h2>
          <p className="muted mt-2">
            Booklet on the left, OMR bubbles on the right. Every answer saves as you mark it, and the server keeps the
            deadline — so a refresh never costs you a paper.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-slate-700">
            {["+4 correct · −1 wrong · 0 blank", "Optional strict OMR mode: no changing a filled bubble", "Section and chapter accuracy after every attempt"].map((t) => (
              <li key={t} className="flex gap-2">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" />
                {t}
              </li>
            ))}
          </ul>
          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wide text-slate-500">
              <span>Full mock paper</span>
              <span>180 questions</span>
            </div>
            <ul className="mt-2 grid grid-cols-2 gap-1.5">
              {SUBJECTS.map((s) => {
                const Ic = s.icon;
                return (
                  <li key={s.name} className="flex items-center justify-between rounded-lg bg-white px-2.5 py-1.5 shadow-sm ring-1 ring-slate-200">
                    <span className="flex items-center gap-1.5 text-[12px] font-semibold text-slate-700">
                      <span className={`grid h-5 w-5 place-items-center rounded-md bg-gradient-to-br ${s.tint} text-white`}>
                        <Ic className="h-3 w-3" />
                      </span>
                      {s.name}
                    </span>
                    <span className="text-[11px] font-bold text-slate-500">45 Q</span>
                  </li>
                );
              })}
            </ul>
          </div>
          <Link href="/practice" className="btn mt-5 w-full sm:w-auto">
            Start a practice test
            <Arrow className="h-4 w-4" />
          </Link>
        </div>

        <div className="card relative overflow-hidden">
          <p className="eyebrow text-rose-600">Weekly plan</p>
          <h2 className="mt-1 font-display text-xl font-extrabold tracking-tight text-slate-900">
            A timetable that reacts to your scores
          </h2>
          <p className="muted mt-2">
            Class 11, Class 12 and droppers get different plans. Chapters you score badly on get more time, and the plan
            warns you when the syllabus stops fitting before the final phase.
          </p>
          <div className="mt-4 space-y-3">
            {[
              ["Physics · Ray optics", 72, "from-teal-500 to-emerald-500"],
              ["Chemistry · Thermodynamics", 45, "from-amber-500 to-orange-500"],
              ["Botany · Plant kingdom", 88, "from-emerald-500 to-lime-500"],
              ["Zoology · Human physiology", 30, "from-rose-500 to-pink-500"],
            ].map(([label, pct, tint]) => (
              <div key={String(label)}>
                <div className="flex items-center justify-between text-[13px]">
                  <span className="font-semibold text-slate-700">{label}</span>
                  <span className="text-slate-500">{pct}%</span>
                </div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full bg-gradient-to-r ${tint}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Sample plan view — your own plan is built from your class, hours and syllabus tracker.
          </p>
          <Link href="/study-plan" className="btn-secondary mt-5 w-full sm:w-auto">
            Build my study plan
          </Link>
        </div>
      </section>

      {/* Trust */}
      <section aria-labelledby="trust" className="rounded-[1.75rem] border border-slate-200 bg-white/70 p-6 shadow-sm sm:p-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow flex items-center gap-2 text-teal-700">
              <PulseRule className="h-3 w-8" /> Why you can rely on it
            </p>
            <h2 id="trust" className="h1 mt-1">Honest by design</h2>
          </div>
          <Link href="/neet" className="text-sm font-bold text-teal-700 hover:underline">
            How NEET-UG works →
          </Link>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {TRUST.map(([title, body]) => (
            <div key={title} className="flex gap-3 rounded-xl bg-white p-4 ring-1 ring-slate-200/80">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
                <Check className="h-3.5 w-3.5" />
              </span>
              <div>
                <p className="text-sm font-bold text-slate-900">{title}</p>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="relative overflow-hidden rounded-[1.75rem] bg-gradient-to-br from-teal-600 via-teal-700 to-indigo-700 px-6 py-10 text-white shadow-xl shadow-teal-900/20 sm:px-10">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <div className="absolute -right-10 -top-16 h-64 w-64 rounded-full bg-white/15 blur-3xl" />
          <div className="absolute -bottom-20 left-10 h-56 w-56 rounded-full bg-indigo-400/25 blur-3xl" />
          <div className="med-crosses absolute inset-0 opacity-[0.06]" />
          <Target className="absolute -bottom-6 right-8 hidden h-40 w-40 text-white/10 lg:block" />
        </div>
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div>
            <h2 className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">Start where you are today.</h2>
            <p className="mt-2 max-w-lg text-sm text-teal-50/90">
              A rank, an estimated range, or just a target score — the predictor works from all three.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/register" className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-bold text-teal-900 shadow-lg shadow-black/20 transition hover:-translate-y-0.5 hover:bg-teal-50">
              Get started free
              <Arrow className="h-4 w-4" />
            </Link>
            <Link href="/colleges" className="inline-flex items-center gap-2 rounded-xl border border-white/30 bg-white/5 px-5 py-3 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-white/15">
              Browse colleges
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
