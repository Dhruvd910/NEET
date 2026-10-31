"use client";

import Link from "next/link";
import { useState } from "react";
import Articles from "@/components/Articles";
import { BadgeId } from "@/components/icons";
import { ErrorBox, FitBadge, Notice, PageHeader, StatusBadge, useApi } from "@/components/ui";
import { api, CATEGORIES, inr, STATES } from "@/lib/api";

type Authority = { code: string; name: string; level: string; state: string | null; website: string | null; quotas: string[] };
type DraftItem = { college_id: number; college_name: string; quota: string; authority: string; historical_fit: string | null;
  estimated_annual_cost_inr?: number | null; note: string | null };
type Draft = { status: string; notice: string; ordering_explained: string; items: DraftItem[]; disclaimer: string; authority_code: string };
type SavedList = { id: number; name: string; authority_code: string; exam_year: number; items: DraftItem[]; notice: string };

const PRIORITY_LABELS: Record<string, string> = {
  government_first: "Government / central colleges first", preferred_states: "My preferred states first",
  lower_cost: "Lower cost first", fit: "Stronger historical fit first",
};

export default function CounsellingPage() {
  const auths = useApi<Authority[]>("/api/counselling/authorities");
  const lists = useApi<SavedList[]>("/api/preference-lists");
  return (
    <div className="space-y-8">
      <PageHeader icon={BadgeId} eyebrow="Admissions desk" title="Counselling centre">How seat allotment works, what to prepare, and a draft preference list you stay in control of.</PageHeader>

      <section>
        <h2 className="h2 mb-3">Counselling authorities</h2>
        <div className="grid gap-3 sm:grid-cols-2">{auths.data?.map((a) => (
          <div key={a.code} className="card text-sm">
            <p className="font-semibold">{a.name} <span className="text-xs font-normal text-slate-500">({a.code})</span></p>
            <p className="text-slate-600">{a.level === "central" ? "All-India counselling" : `State counselling — ${a.state}`} · Quotas: {a.quotas.join(", ")}</p>
            {a.website && <a className="text-teal-700 underline" href={a.website} target="_blank" rel="noreferrer">Official website</a>}
          </div>))}</div>
      </section>

      <section>
        <h2 className="h2 mb-3">Guides</h2>
        <Articles section="counselling" />
      </section>

      <DraftBuilder authorities={auths.data ?? []} onSaved={lists.reload} />

      {!!lists.data?.length && (
        <section>
          <h2 className="h2 mb-3">Your saved draft lists</h2>
          {lists.data.map((l) => <SavedListCard key={l.id} list={l} onChange={lists.reload} />)}
        </section>
      )}
    </div>
  );
}

function DraftBuilder({ authorities, onSaved }: { authorities: Authority[]; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [prios, setPrios] = useState<string[]>(["government_first", "preferred_states", "lower_cost", "fit"]);
  const [err, setErr] = useState<unknown>(null);
  const [form, setForm] = useState({ authority: "MCC", air: "", state_rank: "", category: "", domicile: "", year: String(new Date().getFullYear()), states: [] as string[] });

  const authority = authorities.find((a) => a.code === form.authority);
  const move = (i: number, d: number) => {
    const next = [...items];
    const [x] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, x);
    setItems(next);
  };
  const movePrio = (i: number, d: number) => {
    const next = [...prios];
    const [x] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, x);
    setPrios(next);
  };

  async function build(e: React.FormEvent) {
    e.preventDefault();
    try {
      const quotas = (authority?.quotas ?? ["AIQ"]).filter((q) => ["AIQ", "STATE", "DEEMED", "CENTRAL", "MANAGEMENT"].includes(q));
      const d = await api<Draft>("/api/preference-lists/draft", { method: "POST", json: {
        authority_code: form.authority, priorities: prios,
        predict: { exam_year: Number(form.year), air: form.air ? Number(form.air) : null, state_rank: form.state_rank ? Number(form.state_rank) : null,
          category: form.category || null, domicile_state: form.domicile || null, quotas, preferred_states: form.states },
      } });
      setDraft(d); setItems(d.items); setErr(null);
    } catch (x) { setErr(x); }
  }

  async function save() {
    try {
      await api("/api/preference-lists", { method: "POST", json: {
        name: `${form.authority} draft ${new Date().toLocaleDateString("en-IN")}`, authority_code: form.authority,
        exam_year: Number(form.year), course_code: "MBBS",
        items: items.map(({ college_id, college_name, quota, authority, historical_fit, note }) => ({ college_id, college_name, quota, authority, historical_fit, note })),
      } });
      onSaved();
      alert("Draft saved. Remember: it is not submitted anywhere.");
    } catch { alert("Sign in to save your draft."); }
  }

  return (
    <section className="space-y-4">
      <h2 className="h2">Draft preference list</h2>
      <Notice tone="warn">This tool never submits anything. You must enter and lock your final choices yourself on the official counselling portal.</Notice>
      <form onSubmit={build} className="card grid gap-3 sm:grid-cols-3">
        <div><label className="label" htmlFor="auth">Counselling authority</label>
          <select id="auth" className="input" value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })}>{authorities.map((a) => <option key={a.code} value={a.code}>{a.code}</option>)}</select></div>
        <div><label className="label" htmlFor="air">Official AIR</label><input id="air" type="number" min={1} className="input" value={form.air} onChange={(e) => setForm({ ...form, air: e.target.value })} /></div>
        <div><label className="label" htmlFor="sr">State rank</label><input id="sr" type="number" min={1} className="input" value={form.state_rank} onChange={(e) => setForm({ ...form, state_rank: e.target.value })} /></div>
        <div><label className="label" htmlFor="cat">Category</label><select id="cat" className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}><option value="">OPEN / not provided</option>{CATEGORIES.filter((c) => c !== "OPEN").map((c) => <option key={c}>{c}</option>)}</select></div>
        <div><label className="label" htmlFor="dom">Domicile</label><select id="dom" className="input" value={form.domicile} onChange={(e) => setForm({ ...form, domicile: e.target.value })}><option value="">—</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div><label className="label" htmlFor="yr">NEET year</label><input id="yr" type="number" className="input" value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} /></div>
        <div className="sm:col-span-3">
          <p className="label">Order your priorities (top = most important)</p>
          <ol className="space-y-1 text-sm">{prios.map((p, i) => (
            <li key={p} className="flex items-center gap-2"><span className="w-5 text-slate-500">{i + 1}.</span>{PRIORITY_LABELS[p]}
              <button type="button" aria-label="Move up" className="text-xs underline" onClick={() => movePrio(i, -1)}>↑</button>
              <button type="button" aria-label="Move down" className="text-xs underline" onClick={() => movePrio(i, 1)}>↓</button></li>))}</ol>
        </div>
        <div className="sm:col-span-3"><ErrorBox error={err} /><button className="btn mt-1">Build draft</button></div>
      </form>

      {draft && (
        <div className="card space-y-3">
          <p className="text-sm">{draft.ordering_explained}</p>
          {items.length === 0 ? <p className="text-sm">No historically matching colleges for this authority. Try another authority or check your rank.</p> : (
            <ol className="divide-y divide-slate-100 text-sm">{items.map((it, i) => (
              <li key={`${it.college_id}-${it.quota}`} className="flex flex-wrap items-center gap-2 py-2">
                <span className="w-6 font-semibold">{i + 1}.</span>
                <Link className="flex-1 hover:text-teal-700" href={`/colleges/${it.college_id}`}>{it.college_name}</Link>
                <span className="text-xs text-slate-500">{it.quota}</span>
                {it.historical_fit && <FitBadge fit={it.historical_fit} />}
                <span className="text-xs">{inr(it.estimated_annual_cost_inr ?? null)}</span>
                {it.note && <span className="w-full pl-8 text-xs text-amber-800">{it.note}</span>}
                <span className="flex gap-1"><button className="btn-secondary !px-2 !py-0.5" aria-label="Move up" onClick={() => move(i, -1)}>↑</button>
                  <button className="btn-secondary !px-2 !py-0.5" aria-label="Move down" onClick={() => move(i, 1)}>↓</button>
                  <button className="btn-secondary !px-2 !py-0.5" aria-label="Remove" onClick={() => setItems(items.filter((_, j) => j !== i))}>✕</button></span>
              </li>))}</ol>)}
          <p className="text-xs text-slate-500">{draft.disclaimer}</p>
          <button className="btn" onClick={save} disabled={!items.length}>Save draft</button>
        </div>
      )}
    </section>
  );
}

function SavedListCard({ list, onChange }: { list: SavedList; onChange: () => void }) {
  return (
    <div className="card mb-3 text-sm">
      <div className="flex items-center justify-between"><p className="font-semibold">{list.name} <StatusBadge status="unverified" /></p>
        <button className="text-xs text-red-700 underline" onClick={async () => { await api(`/api/preference-lists/${list.id}`, { method: "DELETE" }); onChange(); }}>Delete</button></div>
      <ol className="mt-2 list-decimal pl-6">{list.items.map((i) => <li key={`${i.college_id}-${i.quota}`}>{i.college_name} · {i.quota}</li>)}</ol>
      <p className="mt-2 text-xs text-amber-800">{list.notice}</p>
    </div>
  );
}
