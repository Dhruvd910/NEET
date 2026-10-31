"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Target } from "@/components/icons";
import { ErrorBox, FitBadge, Notice, PageHeader, StatusBadge, toggleCompare } from "@/components/ui";
import { api, CATEGORIES, inr, num, STATES, type PredictionResult, type PredictionRow } from "@/lib/api";

const QUOTAS = [
  ["AIQ", "All India Quota (MCC)"],
  ["STATE", "State quota (needs domicile)"],
  ["DEEMED", "Deemed universities (MCC)"],
  ["CENTRAL", "Central universities (MCC)"],
  ["MANAGEMENT", "Private management quota"],
] as const;

type Form = {
  course_code: string; exam_year: number; rank_type: "official" | "estimated"; air: string; state_rank: string;
  air_low: string; air_high: string; category: string; pwd: boolean; domicile_state: string; quotas: string[];
  preferred_states: string[]; institution_types: string[]; budget_max_annual: string; hostel_required: boolean;
};

const n = (v: string) => (v === "" ? null : Number(v));

export default function PredictorPage() {
  const [f, setF] = useState<Form>({
    course_code: "MBBS", exam_year: new Date().getFullYear(), rank_type: "official", air: "", state_rank: "", air_low: "",
    air_high: "", category: "", pwd: false, domicile_state: "", quotas: ["AIQ", "STATE"], preferred_states: [],
    institution_types: [], budget_max_annual: "", hostel_required: false,
  });
  const [res, setRes] = useState<PredictionResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    type P = { profile: Record<string, never> | null; exams: Record<string, never>[] };
    api<P>("/api/profile").then(({ profile: p, exams }) => {
      const e = exams.at(-1);
      setF((cur) => ({
        ...cur,
        course_code: p?.preferred_course ?? cur.course_code, category: p?.category ?? "", pwd: !!p?.pwd,
        domicile_state: p?.domicile_state ?? "", budget_max_annual: p?.budget_max_annual ? String(p.budget_max_annual) : "",
        hostel_required: !!p?.hostel_required, exam_year: e?.exam_year ?? cur.exam_year, rank_type: e?.rank_type ?? "official",
        air: e?.air ? String(e.air) : "", state_rank: e?.state_rank ? String(e.state_rank) : "",
        air_low: e?.estimated_rank_low ? String(e.estimated_rank_low) : "", air_high: e?.estimated_rank_high ? String(e.estimated_rank_high) : "",
      }));
      setPrefilled(true);
    }).catch(() => { /* anonymous use is fine */ });
  }, []);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((cur) => ({ ...cur, [k]: v }));
  const toggle = (k: "quotas" | "institution_types", v: string) =>
    set(k, f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v]);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setRes(await api<PredictionResult>("/api/predict", { method: "POST", json: {
        course_code: f.course_code, exam_year: f.exam_year, rank_type: f.rank_type,
        air: f.rank_type === "official" ? n(f.air) : null, state_rank: f.rank_type === "official" ? n(f.state_rank) : null,
        air_low: f.rank_type === "estimated" ? n(f.air_low) : null, air_high: f.rank_type === "estimated" ? n(f.air_high) : null,
        category: f.category || null, pwd: f.pwd, domicile_state: f.domicile_state || null, quotas: f.quotas,
        preferred_states: f.preferred_states, institution_types: f.institution_types,
        budget_max_annual: n(f.budget_max_annual), hostel_required: f.hostel_required,
      } }));
    } catch (x) { setError(x); setRes(null); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Target} eyebrow="Historical cutoff match" title="College predictor">
        We compare your rank with past final-round closing ranks for the <em>same</em> counselling route, quota, category and
        seat type. Results are guidance labels — not chances, and never guarantees.
      </PageHeader>
      {prefilled && <Notice>Filled in from your profile. Changes here are not saved.</Notice>}

      <form onSubmit={run} className="card grid gap-4 md:grid-cols-3">
        <div><label className="label" htmlFor="course">Course</label>
          <select id="course" className="input" value={f.course_code} onChange={(e) => set("course_code", e.target.value)}><option>MBBS</option><option>BDS</option></select></div>
        <div><label className="label" htmlFor="year">NEET year</label>
          <input id="year" type="number" className="input" value={f.exam_year} onChange={(e) => set("exam_year", Number(e.target.value))} /></div>
        <fieldset><legend className="label">Rank type</legend>
          <div className="flex gap-3 text-sm">
            <label className="flex items-center gap-1.5"><input type="radio" checked={f.rank_type === "official"} onChange={() => set("rank_type", "official")} />Official</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={f.rank_type === "estimated"} onChange={() => set("rank_type", "estimated")} />Estimated</label>
          </div></fieldset>
        {f.rank_type === "official" ? (<>
          <div><label className="label" htmlFor="air">All India Rank</label><input id="air" type="number" min={1} className="input" value={f.air} onChange={(e) => set("air", e.target.value)} /></div>
          <div><label className="label" htmlFor="sr">State rank (for state quota, if published)</label><input id="sr" type="number" min={1} className="input" value={f.state_rank} onChange={(e) => set("state_rank", e.target.value)} /></div>
        </>) : (<>
          <div><label className="label" htmlFor="lo">Best-case AIR</label><input id="lo" type="number" min={1} className="input" value={f.air_low} onChange={(e) => set("air_low", e.target.value)} /></div>
          <div><label className="label" htmlFor="hi">Worst-case AIR</label><input id="hi" type="number" min={1} className="input" value={f.air_high} onChange={(e) => set("air_high", e.target.value)} /></div>
        </>)}
        <div><label className="label" htmlFor="cat">Category</label>
          <select id="cat" className="input" value={f.category} onChange={(e) => set("category", e.target.value)}>
            <option value="">Not provided (OPEN)</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></div>
        <div><label className="label" htmlFor="dom">Domicile state</label>
          <select id="dom" className="input" value={f.domicile_state} onChange={(e) => set("domicile_state", e.target.value)}>
            <option value="">Not provided</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div><label className="label" htmlFor="budget">Max yearly budget ₹ (optional)</label><input id="budget" type="number" min={0} step={10000} className="input" value={f.budget_max_annual} onChange={(e) => set("budget_max_annual", e.target.value)} /></div>
        <fieldset className="md:col-span-3"><legend className="label">Counselling routes to include</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">{QUOTAS.map(([q, l]) => (
            <label key={q} className="flex items-center gap-1.5"><input type="checkbox" checked={f.quotas.includes(q)} onChange={() => toggle("quotas", q)} />{l}</label>))}</div></fieldset>
        <fieldset className="md:col-span-2"><legend className="label">Institution types (none = all)</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">{["government", "central", "private", "deemed"].map((t) => (
            <label key={t} className="flex items-center gap-1.5 capitalize"><input type="checkbox" checked={f.institution_types.includes(t)} onChange={() => toggle("institution_types", t)} />{t}</label>))}</div></fieldset>
        <div className="flex flex-col gap-2 text-sm">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.pwd} onChange={(e) => set("pwd", e.target.checked)} />PwD candidate</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={f.hostel_required} onChange={(e) => set("hostel_required", e.target.checked)} />I need a hostel</label>
        </div>
        <div className="md:col-span-3"><button className="btn" disabled={busy}>{busy ? "Comparing…" : "Show historical matches"}</button></div>
      </form>

      <ErrorBox error={error} />
      {res && <Results res={res} />}
    </div>
  );
}

function Results({ res }: { res: PredictionResult }) {
  const total = Object.values(res.counts).reduce((a, b) => a + b, 0);
  return (
    <section className="space-y-5">
      <Notice tone="warn"><strong>Important:</strong> {res.disclaimer}</Notice>
      {res.caveats.map((c) => <Notice key={c}>{c}</Notice>)}
      <p className="muted">{res.method}</p>
      {total === 0 && <p className="card">No colleges matched. Try adding more counselling routes, removing filters, or checking your rank.</p>}
      {Object.entries(res.groups).map(([label, rows]) => rows.length > 0 && (
        <div key={label}>
          <h2 className="h2 mb-2">{label} <span className="text-sm font-normal text-slate-500">({rows.length})</span></h2>
          <div className="grid gap-3">{rows.map((r) => <ResultRow key={`${r.college_id}-${r.counselling_authority}-${r.quota}-${r.seat_type}`} r={r} />)}</div>
        </div>
      ))}
      {res.excluded.length > 0 && (
        <details className="card text-sm">
          <summary className="cursor-pointer font-medium">Why some options are not shown</summary>
          <ul className="mt-2 list-disc pl-5 text-slate-700">{res.excluded.map((e) => <li key={e.reason}>{e.count} × {e.reason}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

function ResultRow({ r }: { r: PredictionRow }) {
  const [added, setAdded] = useState(false);
  return (
    <article className="card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link href={`/colleges/${r.college_id}`} className="font-semibold hover:text-teal-700">{r.college_name}</Link>
          <p className="text-sm text-slate-600">{[r.city, r.state].filter(Boolean).join(", ")} · <span className="capitalize">{r.institution_type}</span> · {r.course_code}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2"><FitBadge fit={r.historical_fit} />{r.is_demo && <StatusBadge status="demo" />}</div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="text-slate-500">Counselling</dt><dd>{r.counselling_authority} · {r.quota}</dd></div>
        <div><dt className="text-slate-500">Category compared</dt><dd>{r.category_used}{r.seat_type !== "GENERAL" && ` · ${r.seat_type}`}</dd></div>
        <div><dt className="text-slate-500">Your rank</dt><dd>{r.student_rank_display}</dd></div>
        <div><dt className="text-slate-500">Confidence</dt><dd className="capitalize" title={r.confidence_reason}>{r.confidence}</dd></div>
        <div><dt className="text-slate-500">Est. yearly cost</dt><dd>{inr(r.estimated_annual_cost_inr)}{r.fee_academic_year && <span className="text-xs text-slate-500"> ({r.fee_academic_year})</span>}</dd></div>
        <div><dt className="text-slate-500">Campus hostel</dt><dd>{r.hostel_on_campus ? "Listed" : "No verified info"}</dd></div>
      </dl>
      <p className="mt-3 text-sm text-slate-800">{r.explanation}</p>
      <p className="mt-1 text-xs text-slate-500">Confidence: {r.confidence_reason}</p>
      {r.caveats.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-amber-800">{r.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium text-teal-800">Historical cutoffs & sources</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="py-1">Year</th><th>Round 1 closing</th><th>Final round</th><th>Opening</th><th>Closing ({r.rank_basis === "AIR" ? "AIR" : "state rank"})</th><th>Source</th></tr></thead>
            <tbody>{r.history.map((h) => (
              <tr key={h.exam_year} className="border-t border-slate-100">
                <td className="py-1">{h.exam_year}</td><td>{num(h.first_round_closing_rank)}</td><td>{h.final_round_name ?? `Round ${h.final_round}`}</td>
                <td>{num(h.opening_rank)}</td><td className="font-medium">{num(h.closing_rank)}</td>
                <td className="text-xs">{h.source_url ? <a className="underline" href={h.source_url} target="_blank" rel="noreferrer">{h.source_name}</a> : h.source_name} <StatusBadge status={h.verification_status} /></td>
              </tr>))}</tbody>
          </table>
        </div>
      </details>
      <div className="mt-3 flex gap-2">
        <button className="btn-secondary" onClick={() => { toggleCompare(r.college_id); setAdded(true); }}>{added ? "Added to compare" : "+ Compare"}</button>
        <button className="btn-secondary" onClick={() => api(`/api/saved-colleges/${r.college_id}`, { method: "POST" }).catch(() => alert("Sign in to save colleges."))}>☆ Save</button>
      </div>
    </article>
  );
}
