"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Hospital } from "@/components/icons";
import { CollegeCard, Empty, ErrorBox, Loading, PageHeader, getCompareIds, toggleCompare, useApi } from "@/components/ui";
import { api, type CollegeCardT } from "@/lib/api";

type ListResp = { total: number; page: number; page_size: number; items: CollegeCardT[] };

export default function CollegesPage() {
  const facets = useApi<{ states: string[]; institution_types: string[] }>("/api/colleges/facets");
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [course, setCourse] = useState("");
  const [itype, setItype] = useState("");
  const [page, setPage] = useState(1);
  const [compare, setCompare] = useState<number[]>([]);
  const [saved, setSaved] = useState<number[]>([]);

  useEffect(() => {
    setCompare(getCompareIds());
    api<{ college: CollegeCardT }[]>("/api/saved-colleges").then((s) => setSaved(s.map((x) => x.college.id))).catch(() => {});
  }, []);

  const params = new URLSearchParams({ page: String(page), page_size: "12", ...(q && { q }), ...(state && { state }), ...(course && { course }), ...(itype && { institution_type: itype }) });
  const { data, error, loading } = useApi<ListResp>(`/api/colleges?${params}`);

  async function save(id: number) {
    try {
      if (saved.includes(id)) { await api(`/api/saved-colleges/${id}`, { method: "DELETE" }); setSaved(saved.filter((x) => x !== id)); }
      else { await api(`/api/saved-colleges/${id}`, { method: "POST" }); setSaved([...saved, id]); }
    } catch { alert("Sign in to save colleges to your shortlist."); }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div className="space-y-5">
      <PageHeader icon={Hospital} eyebrow="Medical college directory" title="Colleges">Browse medical and dental colleges. Every figure links back to its source and freshness.</PageHeader>
      <div className="card grid gap-3 sm:grid-cols-4">
        <div className="sm:col-span-4"><label className="label" htmlFor="q">Search name or city</label>
          <input id="q" className="input" value={q} placeholder="e.g. Government Medical College" onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        <div><label className="label" htmlFor="st">State</label>
          <select id="st" className="input" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}><option value="">All</option>{facets.data?.states.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div><label className="label" htmlFor="co">Course</label>
          <select id="co" className="input" value={course} onChange={(e) => { setCourse(e.target.value); setPage(1); }}><option value="">All</option><option>MBBS</option><option>BDS</option></select></div>
        <div><label className="label" htmlFor="it">Type</label>
          <select id="it" className="input capitalize" value={itype} onChange={(e) => { setItype(e.target.value); setPage(1); }}><option value="">All</option>{facets.data?.institution_types.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div className="flex items-end">{compare.length > 0 && <Link className="btn w-full" href="/compare">Compare ({compare.length})</Link>}</div>
      </div>

      <ErrorBox error={error} />
      {loading ? <Loading /> : data && data.items.length === 0 ? <Empty title="No colleges match these filters" /> : (
        <>
          <p className="muted">{data?.total} colleges</p>
          <div className="grid gap-4 md:grid-cols-2">
            {data?.items.map((c) => (
              <CollegeCard key={c.id} c={c} saved={saved.includes(c.id)} onSave={() => save(c.id)}
                onCompare={() => setCompare(toggleCompare(c.id))}
                extra={compare.includes(c.id) ? <p className="text-xs text-teal-700">In compare list</p> : null} />
            ))}
          </div>
          {pages > 1 && (
            <nav className="flex items-center justify-center gap-3" aria-label="Pagination">
              <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="text-sm">Page {page} of {pages}</span>
              <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
