"use client";

import { useState } from "react";
import { Clipboard } from "@/components/icons";
import { ErrorBox, Loading, PageHeader, SignInPrompt, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { ArticlesPanel, CollegesPanel, ImportsPanel, ReadinessPanel, RulesPanel, SourcesPanel } from "./panels";

type Stats = { colleges: number; demo_colleges: number; cutoff_records: number; cutoffs_by_status: Record<string, number>;
  open_issues: number; pending_reviews: number; documents: number };
type Issue = { id: number; entity_type: string; entity_id: number | null; issue_type: string; details: Record<string, unknown>; created_at: string };
type Review = { id: number; college_id: number; rating: number; body: string };

const TABS = ["Overview", "Imports", "Sources", "Eligibility rules", "Info pages", "Colleges", "Issues & reviews"] as const;

export default function AdminPage() {
  const stats = useApi<Stats>("/api/admin/stats");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const issues = useApi<Issue[]>(stats.data && tab === "Issues & reviews" ? "/api/admin/issues" : null);
  const reviews = useApi<Review[]>(stats.data && tab === "Issues & reviews" ? "/api/admin/reviews" : null);
  const [err, setErr] = useState<unknown>(null);

  if (stats.loading) return <Loading />;
  if (stats.error) return <SignInPrompt error={stats.error} />;
  const s = stats.data!;
  const changed = () => stats.reload();
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); setErr(null); issues.reload(); reviews.reload(); stats.reload(); } catch (x) { setErr(x); }
  };

  return (
    <div className="space-y-6">
      <PageHeader icon={Clipboard} eyebrow="Administration" title="Data & admin">Imports, source terms, rules, review queues and data quality. Every change is audit-logged.</PageHeader>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["Colleges", `${s.colleges} (${s.demo_colleges} demo)`], ["Cutoff records", s.cutoff_records], ["Open issues", s.open_issues], ["Pending reviews", s.pending_reviews]].map(([k, v]) => (
          <div key={k} className="card"><p className="muted">{k}</p><p className="text-xl font-semibold">{v}</p></div>))}
      </div>

      <div role="tablist" aria-label="Admin sections" className="flex gap-1 overflow-x-auto border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === t ? "border-teal-700 font-medium text-teal-800" : "border-transparent text-slate-600 hover:text-slate-900"}`}>{t}</button>))}
      </div>

      <div key={tab}>
        {tab === "Overview" && (
          <div className="space-y-3">
            <ReadinessPanel />
            <p className="text-xs text-slate-500">Cutoffs by status: {Object.entries(s.cutoffs_by_status).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
          </div>)}
        {tab === "Imports" && <ImportsPanel onChange={changed} />}
        {tab === "Sources" && <SourcesPanel onChange={changed} />}
        {tab === "Eligibility rules" && <RulesPanel onChange={changed} />}
        {tab === "Info pages" && <ArticlesPanel onChange={changed} />}
        {tab === "Colleges" && <CollegesPanel onChange={changed} />}
        {tab === "Issues & reviews" && (
          <div className="space-y-4">
            <ErrorBox error={err} />
            <section className="card">
              <h2 className="h2 mb-2">Open data-quality issues</h2>
              {!issues.data?.length ? <p className="muted">No open issues.</p> : (
                <ul className="divide-y divide-slate-100 text-sm">{issues.data.map((i) => (
                  <li key={i.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
                    <div className="min-w-0"><p className="font-medium">{i.issue_type.replaceAll("_", " ")} · {i.entity_type}{i.entity_id && ` #${i.entity_id}`}</p>
                      <pre className="mt-1 max-w-xl overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(i.details, null, 1)}</pre></div>
                    <div className="flex gap-2">
                      <button className="btn-secondary" onClick={() => act(() => api(`/api/admin/issues/${i.id}`, { method: "PATCH", json: { status: "resolved" } }))}>Resolve</button>
                      <button className="btn-secondary" onClick={() => act(() => api(`/api/admin/issues/${i.id}`, { method: "PATCH", json: { status: "ignored" } }))}>Ignore</button>
                    </div></li>))}</ul>)}
            </section>
            <section className="card">
              <h2 className="h2 mb-2">Reviews awaiting moderation</h2>
              {!reviews.data?.length ? <p className="muted">Queue is empty.</p> : (
                <ul className="divide-y divide-slate-100 text-sm">{reviews.data.map((r) => (
                  <li key={r.id} className="py-2"><p>College #{r.college_id} · {r.rating}★</p><p className="text-slate-700">{r.body}</p>
                    <div className="mt-1 flex gap-2">
                      <button className="btn-secondary" onClick={() => act(() => api(`/api/admin/reviews/${r.id}`, { method: "PATCH", json: { status: "approved" } }))}>Approve</button>
                      <button className="btn-secondary" onClick={() => act(() => api(`/api/admin/reviews/${r.id}`, { method: "PATCH", json: { status: "rejected", note: "Violates guidelines" } }))}>Reject</button>
                    </div></li>))}</ul>)}
            </section>
          </div>)}
      </div>
    </div>
  );
}
