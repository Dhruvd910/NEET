"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HeartPulse } from "@/components/icons";
import { Empty, ErrorBox, Loading, Notice, PageHeader, SignInPrompt, useApi } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type Analytics = {
  notice: string; count: number;
  history: { id: number; name: string; provider: string | null; test_date: string; total_score: number; max_score: number; percent: number; subjects: Record<string, number> }[];
  best_percent?: number; latest_percent?: number; average_percent?: number;
  trend: { recent_avg_percent: number; earlier_avg_percent: number; change_points: number; direction: string } | null;
  subjects: Record<string, { average_percent: number; latest_percent: number; best_percent: number; tests: number }>;
  weak_topics: [string, number][]; priorities: string[];
  estimate: { label: string; score_band_out_of_720: [number, number]; assumptions: string[] } | null;
};
const SUBJECTS = [["Physics", 180], ["Chemistry", 180], ["Biology", 360]] as const;
const COLORS = { percent: "#0f766e", Physics: "#4f46e5", Chemistry: "#c2410c", Biology: "#15803d" };

export default function MockTestsPage() {
  const { data, error, loading, reload } = useApi<Analytics>("/api/mock-tests/analytics");
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState(false);

  if (loading) return <Loading />;
  if (error) return <SignInPrompt error={error} />;

  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const subjects = SUBJECTS.filter(([s]) => f.get(s) !== "").map(([s, max]) => ({
      subject: s, score: Number(f.get(s)), max_score: max,
      weak_topics: String(f.get(`${s}-topics`) ?? "").split(",").map((t) => t.trim()).filter(Boolean),
    }));
    try {
      await api("/api/mock-tests", { method: "POST", json: {
        name: f.get("name"), provider: f.get("provider") || null, test_date: f.get("test_date"),
        total_score: Number(f.get("total_score")), max_score: Number(f.get("max_score") || 720),
        percentile: f.get("percentile") ? Number(f.get("percentile")) : null, notes: f.get("notes") || null, subjects,
      } });
      form.reset(); setErr(null); setOpen(false); reload();
    } catch (x) { setErr(x); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this test?")) return;
    await api(`/api/mock-tests/${id}`, { method: "DELETE" });
    reload();
  }

  const chart = data?.history.map((h) => ({ date: fmtDate(h.test_date), percent: h.percent, ...h.subjects })) ?? [];
  return (
    <div className="space-y-6">
      <PageHeader icon={HeartPulse} eyebrow="Score vitals" title="Mock-test tracker">Log every full-length test to see trends and where to focus.</PageHeader>
      <Notice>{data?.notice}</Notice>
      <button className="btn" onClick={() => setOpen(!open)}>{open ? "Close" : "+ Add a test"}</button>

      {open && (
        <form onSubmit={add} className="card grid gap-3 sm:grid-cols-3">
          <div><label className="label" htmlFor="name">Test name</label><input id="name" name="name" required className="input" placeholder="Full syllabus test 3" /></div>
          <div><label className="label" htmlFor="provider">Provider (optional)</label><input id="provider" name="provider" className="input" /></div>
          <div><label className="label" htmlFor="test_date">Date</label><input id="test_date" name="test_date" type="date" required className="input" max={new Date().toISOString().slice(0, 10)} /></div>
          <div><label className="label" htmlFor="total_score">Total score</label><input id="total_score" name="total_score" type="number" required className="input" /></div>
          <div><label className="label" htmlFor="max_score">Out of</label><input id="max_score" name="max_score" type="number" defaultValue={720} className="input" /></div>
          <div><label className="label" htmlFor="percentile">Provider percentile (optional)</label><input id="percentile" name="percentile" type="number" step="0.01" className="input" /></div>
          {SUBJECTS.map(([s, max]) => (
            <div key={s} className="space-y-1">
              <label className="label" htmlFor={s}>{s} (out of {max})</label><input id={s} name={s} type="number" className="input" />
              <input name={`${s}-topics`} className="input" placeholder="Topics to revisit, comma-separated" aria-label={`${s} topics to revisit`} />
            </div>))}
          <div className="sm:col-span-3"><label className="label" htmlFor="notes">Notes</label><textarea id="notes" name="notes" className="input" rows={2} /></div>
          <div className="sm:col-span-3"><ErrorBox error={err} /><button className="btn mt-2">Save test</button></div>
        </form>
      )}

      {!data?.count ? <Empty title="No mock tests yet">Add your first test to see your progress.</Empty> : (<>
        <div className="grid gap-4 sm:grid-cols-4">
          {[["Latest", data.latest_percent], ["Best", data.best_percent], ["Average", data.average_percent]].map(([l, v]) => (
            <div key={l} className="card"><p className="muted">{l}</p><p className="text-2xl font-semibold">{v}%</p></div>))}
          <div className="card"><p className="muted">Trend (last 3 vs earlier)</p>
            <p className="text-2xl font-semibold capitalize">{data.trend?.direction ?? "—"}</p>
            {data.trend && <p className="text-xs text-slate-500">{data.trend.change_points > 0 ? "+" : ""}{data.trend.change_points} points</p>}</div>
        </div>

        <section className="card">
          <h2 className="h2 mb-3">Score history (% of maximum)</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chart} margin={{ left: -16, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" fontSize={12} /><YAxis domain={[0, 100]} fontSize={12} />
                <Tooltip /><Legend />
                <Line type="monotone" dataKey="percent" name="Total" stroke={COLORS.percent} strokeWidth={3} />
                {SUBJECTS.map(([s]) => <Line key={s} type="monotone" dataKey={s} stroke={COLORS[s]} strokeDasharray="4 3" />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="card">
            <h2 className="h2">Subjects</h2>
            <table className="mt-2 w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th>Subject</th><th>Average</th><th>Latest</th><th>Best</th></tr></thead>
              <tbody>{Object.entries(data.subjects).sort((a, b) => a[1].average_percent - b[1].average_percent).map(([s, v]) => (
                <tr key={s} className="border-t border-slate-100"><td className="py-1">{s}</td><td>{v.average_percent}%</td><td>{v.latest_percent}%</td><td>{v.best_percent}%</td></tr>))}</tbody></table>
          </section>
          <section className="card">
            <h2 className="h2">Suggested revision priorities</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{data.priorities.map((p) => <li key={p}>{p}</li>)}</ul>
          </section>
        </div>

        {data.estimate && (
          <section className="card border-amber-300">
            <h2 className="h2">{data.estimate.label}</h2>
            <p className="mt-1 text-lg">Recent range: <strong>{data.estimate.score_band_out_of_720[0]}–{data.estimate.score_band_out_of_720[1]}</strong> / 720</p>
            <ul className="mt-2 list-disc pl-5 text-xs text-slate-600">{data.estimate.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          </section>
        )}

        <section className="card">
          <h2 className="h2 mb-2">All tests</h2>
          <ul className="divide-y divide-slate-100 text-sm">{[...data.history].reverse().map((h) => (
            <li key={h.id} className="flex items-center justify-between py-2">
              <span>{fmtDate(h.test_date)} · {h.name}{h.provider && ` (${h.provider})`} — <strong>{h.total_score}/{h.max_score}</strong></span>
              <button className="text-xs text-red-700 underline" onClick={() => remove(h.id)}>Delete</button></li>))}</ul>
        </section>
      </>)}
    </div>
  );
}
