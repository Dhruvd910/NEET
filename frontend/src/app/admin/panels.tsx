"use client";

import { useState } from "react";
import { ErrorBox, Notice, StatusBadge, useApi } from "@/components/ui";
import { api, csrfHeader, fmtDate } from "@/lib/api";

// ---------------------------------------------------------------- shared

export async function upload(path: string, form: HTMLFormElement) {
  const res = await fetch(path, { method: "POST", body: new FormData(form), credentials: "include", headers: csrfHeader("POST") });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? `Upload failed (${res.status})`);
  return data;
}

function useAction(after: () => void) {
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  /** Runs an admin action; resolves to true on success so callers can reset their form. */
  async function run(fn: () => Promise<unknown>, ok: string | ((r: unknown) => string)): Promise<boolean> {
    try {
      const r = await fn();
      setMsg(typeof ok === "string" ? ok : ok(r));
      setErr(null);
      after();
      return true;
    } catch (x) {
      setErr(x);
      setMsg(null);
      return false;
    }
  }
  const feedback = <>{msg && <Notice>{msg}</Notice>}<ErrorBox error={err} /></>;
  return { run, feedback };
}

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-800", todo: "bg-red-100 text-red-800", warn: "bg-amber-100 text-amber-900",
};

// ---------------------------------------------------------------- readiness

type Readiness = { ready: boolean; items: { key: string; label: string; status: string; detail: string }[] };

export function ReadinessPanel() {
  const r = useApi<Readiness>("/api/admin/readiness");
  if (!r.data) return <ErrorBox error={r.error} />;
  return (
    <section className="card">
      <h2 className="h2 mb-1">Go-live readiness</h2>
      <p className="muted mb-3">
        {r.data.ready ? "No blocking items. Review the warnings before launch." :
          "Items marked “to do” block real use. Each one is computed from the data and server configuration."}
      </p>
      <ul className="divide-y divide-slate-100 text-sm">
        {r.data.items.map((i) => (
          <li key={i.key} className="flex flex-wrap items-start gap-3 py-2">
            <span className={`w-14 shrink-0 rounded px-1.5 py-0.5 text-center text-xs font-medium ${STATUS_STYLE[i.status]}`}>
              {i.status === "todo" ? "to do" : i.status}</span>
            <div className="min-w-0 flex-1"><p className="font-medium">{i.label}</p><p className="text-slate-600">{i.detail}</p></div>
          </li>))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- imports & documents

type Source = { id: number; code: string; name: string; kind: string; base_url: string | null; terms_url: string | null;
  terms_note: string | null; attribution_text: string | null; usage_status: string; automated_access_permitted: boolean;
  terms_reviewed_at: string | null };
type Job = { id: number; kind: string; status: string; filename: string | null; started_at: string; rows_read: number;
  inserted: number; updated: number; skipped: number; errors: { row: number | null; error: string }[] };
type Doc = { id: number; title: string; doc_type: string; authority: string | null; exam_year: number | null; version: number;
  chunks: number; embedded: number; needs_ocr: boolean; created_at: string };

const TABLES = {
  cutoffs: "college_code or college_name, course, authority, exam_year, round, quota, category, closing_rank (+ opening_rank, seat_type, rank_basis, domicile_required, round_name)",
  seat_matrix: "college_code or college_name, course, authority, exam_year, round, quota, category, seats (+ seat_type)",
  fees: "college_code or college_name, academic_year (2025-26), fee_type, amount_inr, period (+ course, quota, mandatory, refundable, note)",
} as const;

export function ImportsPanel({ onChange }: { onChange: () => void }) {
  const sources = useApi<Source[]>("/api/admin/data-sources");
  const jobs = useApi<Job[]>("/api/admin/imports");
  const docs = useApi<Doc[]>("/api/admin/documents");
  const [kind, setKind] = useState<keyof typeof TABLES>("cutoffs");
  const refresh = () => { jobs.reload(); docs.reload(); onChange(); };
  const { run, feedback } = useAction(refresh);
  const allowed = sources.data?.filter((s) => s.usage_status === "allowed") ?? [];

  return (
    <div className="space-y-4">
      {feedback}
      <div className="grid gap-4 md:grid-cols-2">
        <form className="card space-y-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget;
          run(() => upload(`/api/admin/imports/${kind}`, f), (r) => { const j = r as Job; return `Import ${j.status}: ${j.inserted} new, ${j.updated} updated, ${j.skipped} skipped.`; }); }}>
          <h2 className="h2">Import a table (CSV / XLSX)</h2>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as keyof typeof TABLES)} aria-label="Table type">
            <option value="cutoffs">Cutoffs / closing ranks</option><option value="seat_matrix">Seat matrix</option><option value="fees">Fees</option>
          </select>
          <p className="text-xs text-slate-500">Columns: {TABLES[kind]}. Templates are in <code>backend/samples/</code>. Rows start as “unverified”.</p>
          <input className="input" type="file" name="file" accept=".csv,.xlsx" required aria-label="File" />
          <select className="input" name="data_source_code" required defaultValue="" aria-label="Data source">
            <option value="" disabled>Data source (terms reviewed)…</option>
            {allowed.map((s) => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)}
          </select>
          {sources.data && allowed.filter((s) => s.kind !== "demo").length === 0 &&
            <p className="text-xs text-amber-800">No real source has its terms of use reviewed yet. Do that on the Sources tab first.</p>}
          <input className="input" name="source_name" placeholder="Document name, e.g. MCC Round 2 allotment 2025" required minLength={3} />
          <input className="input" name="source_url" placeholder="Official URL of this document" type="url" />
          <label className="text-sm">Publication date <input className="input" type="date" name="publication_date" /></label>
          <button className="btn">Import</button>
        </form>
        <form className="card space-y-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget;
          run(() => upload("/api/admin/documents", f), (r) => `Indexed “${(r as { title: string }).title}” (${(r as { chunks: number }).chunks} passages).`); }}>
          <h2 className="h2">Upload an official document (PDF / TXT)</h2>
          <p className="text-xs text-slate-500">Indexed for the assistant with page references. Scanned pages are OCR&apos;d when Tesseract is installed, and flagged for review.</p>
          <input className="input" type="file" name="file" accept=".pdf,.txt,.md" required aria-label="Document" />
          <input className="input" name="title" placeholder="Title, e.g. NEET-UG 2026 Information Bulletin" required />
          <input className="input" name="url" placeholder="Official URL" type="url" />
          <div className="grid grid-cols-3 gap-2">
            <input className="input" name="authority" placeholder="NTA, MCC…" aria-label="Authority" />
            <input className="input" name="exam_year" type="number" placeholder="Year" aria-label="Exam year" />
            <select className="input" name="doc_type" defaultValue="notice" aria-label="Document type"><option>notice</option><option>bulletin</option><option>prospectus</option><option>seat_matrix</option><option>scheme</option></select>
          </div>
          <label className="text-sm">Publication date <input className="input" type="date" name="publication_date" /></label>
          <button className="btn">Upload</button>
        </form>
      </div>

      <section className="card">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="h2">Documents</h2>
          <button className="btn-secondary" onClick={() => run(() => api("/api/admin/embeddings/backfill", { method: "POST" }),
            (r) => `Embedded ${(r as { embedded: number }).embedded} passage(s).`)}>Build semantic index</button>
        </div>
        <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-xs text-slate-500"><tr><th>Title</th><th>Type</th><th>Year</th><th>v</th><th>Passages</th><th>Semantic</th><th>OCR</th></tr></thead>
          <tbody>{docs.data?.map((d) => (
            <tr key={d.id} className="border-t border-slate-100"><td className="py-1">{d.title}</td><td>{d.doc_type}</td><td>{d.exam_year ?? "—"}</td>
              <td>{d.version}</td><td>{d.chunks}</td><td>{d.embedded}/{d.chunks}</td>
              <td>{d.needs_ocr ? <button className="btn-secondary !px-2 !py-0.5 text-xs" onClick={() => run(() => api(`/api/admin/documents/${d.id}/ocr`, { method: "POST" }),
                (r) => `OCR ${(r as Job).status}.`)}>Run OCR</button> : "—"}</td></tr>))}</tbody>
        </table></div>
      </section>

      <section className="card">
        <h2 className="h2 mb-2">Recent imports</h2>
        <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left text-sm">
          <thead className="text-xs text-slate-500"><tr><th>#</th><th>Kind</th><th>File</th><th>Status</th><th>Read</th><th>New</th><th>Updated</th><th>Skipped</th><th>When</th></tr></thead>
          <tbody>{jobs.data?.map((j) => (
            <tr key={j.id} className="border-t border-slate-100 align-top"><td className="py-1">{j.id}</td><td>{j.kind}</td><td>{j.filename}</td>
              <td>{j.status}{j.errors.length > 0 && <details><summary className="cursor-pointer text-xs text-red-700">{j.errors.length} errors</summary>
                <ul className="text-xs">{j.errors.slice(0, 10).map((e, i) => <li key={i}>Row {e.row ?? "–"}: {e.error}</li>)}</ul></details>}</td>
              <td>{j.rows_read}</td><td>{j.inserted}</td><td>{j.updated}</td><td>{j.skipped}</td><td>{fmtDate(j.started_at)}</td></tr>))}</tbody>
        </table></div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- sources & terms of use

export function SourcesPanel({ onChange }: { onChange: () => void }) {
  const sources = useApi<Source[]>("/api/admin/data-sources");
  const [editing, setEditing] = useState<number | null>(null);
  const refresh = () => { sources.reload(); onChange(); };
  const { run, feedback } = useAction(refresh);

  return (
    <div className="space-y-4">
      <Notice>
        Record the outcome of reading each source&apos;s terms of use before importing from it. Imports are refused for
        sources that are not marked “allowed”. This records your decision; it is not legal advice.
      </Notice>
      {feedback}
      <ul className="space-y-3">
        {sources.data?.map((s) => (
          <li key={s.id} className="card text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><p className="font-medium">{s.code} — {s.name}</p>
                <p className="text-slate-600">{s.kind.replace("_", " ")} · {s.base_url ? <a className="underline" href={s.base_url} target="_blank" rel="noreferrer">{s.base_url}</a> : "no URL"}</p></div>
              <div className="flex items-center gap-2"><StatusBadge status={s.usage_status} />
                {s.kind !== "demo" && <button className="btn-secondary !px-2 !py-1" onClick={() => setEditing(editing === s.id ? null : s.id)}>Review terms</button>}</div>
            </div>
            {s.terms_note && <p className="mt-1 text-slate-700">{s.terms_note}</p>}
            {s.terms_reviewed_at && <p className="text-xs text-slate-500">Reviewed {fmtDate(s.terms_reviewed_at)}{s.terms_url && <> · <a className="underline" href={s.terms_url} target="_blank" rel="noreferrer">terms</a></>}</p>}
            {editing === s.id && (
              <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget);
                run(() => api(`/api/admin/data-sources/${s.id}/terms`, { method: "PATCH", json: {
                  usage_status: f.get("usage_status"), terms_url: f.get("terms_url") || null, terms_note: f.get("terms_note"),
                  attribution_text: f.get("attribution_text") || null, automated_access_permitted: f.get("automated") === "on" } }),
                  `Saved terms review for ${s.code}.`).then((ok) => ok && setEditing(null)); }}>
                <select className="input" name="usage_status" defaultValue={s.usage_status} aria-label="Usage status">
                  <option value="allowed">allowed</option><option value="restricted">restricted</option><option value="prohibited">prohibited</option><option value="unreviewed">unreviewed</option></select>
                <input className="input" name="terms_url" type="url" placeholder="Link to the terms / copyright policy" defaultValue={s.terms_url ?? ""} />
                <textarea className="input sm:col-span-2" name="terms_note" required minLength={10} rows={3} placeholder="What the terms allow (reuse, attribution, automated access) and who reviewed them" defaultValue={s.terms_note ?? ""} />
                <input className="input" name="attribution_text" placeholder="Required attribution text, if any" defaultValue={s.attribution_text ?? ""} />
                <label className="flex items-center gap-2"><input type="checkbox" name="automated" defaultChecked={s.automated_access_permitted} /> Automated downloading permitted</label>
                <button className="btn sm:col-span-2">Save review</button>
              </form>)}
          </li>))}
      </ul>
      <form className="card grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
        run(() => api("/api/admin/data-sources", { method: "POST", json: { code: f.get("code"), name: f.get("name"), kind: f.get("kind"), base_url: f.get("base_url") || null } }),
          "Source added. Review its terms before importing.").then((ok) => ok && form.reset()); }}>
        <h2 className="h2 sm:col-span-4">Add a data source</h2>
        <input className="input" name="code" placeholder="Code, e.g. AACCC" required pattern="[A-Za-z0-9_-]+" />
        <input className="input" name="name" placeholder="Name" required minLength={3} />
        <select className="input" name="kind" defaultValue="official_portal" aria-label="Kind"><option value="official_portal">official portal</option><option value="college_site">college website</option><option value="licensed_api">licensed API</option><option value="other">other</option></select>
        <input className="input" name="base_url" type="url" placeholder="Website" />
        <button className="btn sm:col-span-4">Add source</button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- eligibility rules

type Rule = { id: number; authority: string; exam_year: number; quota: string; rule_key: string; value: boolean | string;
  source_name: string; source_url: string | null; verification_status: string; last_verified_at: string | null };
type Rules = { known_rules: Record<string, string>; rules: Rule[]; gaps: { authority: string; authority_id: number; exam_year: number; quota: string }[];
  authorities: { id: number; code: string; quotas: string[] }[] };

export function RulesPanel({ onChange }: { onChange: () => void }) {
  const r = useApi<Rules>("/api/admin/eligibility-rules");
  const refresh = () => { r.reload(); onChange(); };
  const { run, feedback } = useAction(refresh);
  const [prefill, setPrefill] = useState<{ authority_id: number; exam_year: number; quota: string } | null>(null);
  if (!r.data) return <ErrorBox error={r.error} />;
  const d = r.data;

  return (
    <div className="space-y-4">
      <Notice>
        Without a <em>verified</em> “open_category_accessible” rule, reserved-category students are only compared with
        their own category&apos;s cutoffs. Enter each rule from the official counselling scheme for that authority and year,
        then verify it after checking the source.
      </Notice>
      {feedback}
      <section className="card">
        <h2 className="h2 mb-2">Missing rules ({d.gaps.length})</h2>
        {d.gaps.length === 0 ? <p className="muted">Every authority/year/quota with real cutoffs has a verified rule.</p> : (
          <ul className="flex flex-wrap gap-2 text-sm">{d.gaps.map((g) => (
            <li key={`${g.authority_id}-${g.exam_year}-${g.quota}`}>
              <button className="btn-secondary !px-2 !py-1" onClick={() => setPrefill(g)}>{g.authority} {g.exam_year} {g.quota}</button></li>))}</ul>)}
      </section>
      <form key={JSON.stringify(prefill)} className="card grid gap-2 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget);
        const key = f.get("rule_key") as string; const raw = f.get("value") as string;
        run(() => api("/api/admin/eligibility-rules", { method: "PUT", json: {
          authority_id: Number(f.get("authority_id")), exam_year: Number(f.get("exam_year")), quota: f.get("quota"), rule_key: key,
          value: key === "open_category_accessible" ? raw === "true" : raw, description: f.get("description") || null,
          source_name: f.get("source_name"), source_url: f.get("source_url"), publication_date: f.get("publication_date") || null } }),
          "Rule saved as unverified. Verify it below after checking the source."); }}>
        <h2 className="h2 sm:col-span-3">Enter a rule</h2>
        <select className="input" name="authority_id" required defaultValue={prefill?.authority_id ?? ""} aria-label="Authority">
          <option value="" disabled>Authority…</option>{d.authorities.map((a) => <option key={a.id} value={a.id}>{a.code}</option>)}</select>
        <input className="input" name="exam_year" type="number" required placeholder="Exam year" defaultValue={prefill?.exam_year} />
        <input className="input" name="quota" required placeholder="Quota (AIQ, STATE… or * for all)" defaultValue={prefill?.quota} />
        <select className="input" name="rule_key" aria-label="Rule">{Object.keys(d.known_rules).map((k) => <option key={k}>{k}</option>)}</select>
        <select className="input" name="value" aria-label="Value"><option value="true">true / allowed</option><option value="false">false / not allowed</option><option>AIR</option><option>STATE_RANK</option></select>
        <input className="input" name="publication_date" type="date" aria-label="Publication date" />
        <input className="input sm:col-span-3" name="source_name" required minLength={3} placeholder="Source document, e.g. MCC UG counselling scheme 2025, clause 7" />
        <input className="input sm:col-span-3" name="source_url" type="url" required placeholder="Official URL" />
        <input className="input sm:col-span-3" name="description" placeholder="Note (optional)" />
        <button className="btn sm:col-span-3">Save rule</button>
      </form>
      <section className="card">
        <h2 className="h2 mb-2">Rules</h2>
        {d.rules.length === 0 ? <p className="muted">No real rules entered yet (demo rules are hidden).</p> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th>Authority</th><th>Year</th><th>Quota</th><th>Rule</th><th>Value</th><th>Source</th><th>Status</th><th /></tr></thead>
            <tbody>{d.rules.map((x) => (
              <tr key={x.id} className="border-t border-slate-100"><td className="py-1">{x.authority}</td><td>{x.exam_year}</td><td>{x.quota}</td><td>{x.rule_key}</td>
                <td>{String(x.value)}</td><td>{x.source_url ? <a className="underline" href={x.source_url} target="_blank" rel="noreferrer">{x.source_name}</a> : x.source_name}</td>
                <td><StatusBadge status={x.verification_status} /></td>
                <td>{x.verification_status !== "verified" && <button className="btn-secondary !px-2 !py-0.5 text-xs" onClick={() => run(() => api("/api/admin/verify",
                  { method: "POST", json: { entity_type: "eligibility_rule", entity_id: x.id, status: "verified" } }), "Rule verified.")}>Verify</button>}</td></tr>))}</tbody>
          </table></div>)}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- info pages

type Article = { id: number; section: string; slug: string; title: string; body: string; exam_year: number | null; source_name: string;
  source_url: string | null; source_document_id: number | null; verification_status: string; last_verified_at: string | null };

export function ArticlesPanel({ onChange }: { onChange: () => void }) {
  const arts = useApi<Article[]>("/api/admin/info-articles");
  const [open, setOpen] = useState<number | null>(null);
  const refresh = () => { arts.reload(); onChange(); };
  const { run, feedback } = useAction(refresh);

  return (
    <div className="space-y-4">
      <Notice>
        Check each page against the current NTA Information Bulletin (upload it on the Imports tab first). Set the exam
        year and source, edit the text if needed, then mark it verified. Any later edit sends it back for review.
      </Notice>
      {feedback}
      <ul className="space-y-2">
        {arts.data?.map((a) => (
          <li key={a.id} className="card text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button className="text-left font-medium hover:underline" onClick={() => setOpen(open === a.id ? null : a.id)}>{a.section} · {a.title}</button>
              <div className="flex items-center gap-2"><span className="text-xs text-slate-500">{a.exam_year ?? "no year"}</span><StatusBadge status={a.verification_status} /></div>
            </div>
            {open === a.id && (
              <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget);
                run(() => api(`/api/admin/info-articles/${a.id}`, { method: "PATCH", json: {
                  title: f.get("title"), body: f.get("body"), exam_year: f.get("exam_year") ? Number(f.get("exam_year")) : null,
                  source_name: f.get("source_name"), source_url: f.get("source_url") || null,
                  source_document_id: f.get("source_document_id") ? Number(f.get("source_document_id")) : null } }), "Saved. Now verify it."); }}>
                <input className="input" name="title" defaultValue={a.title} required aria-label="Title" />
                <textarea className="input" name="body" defaultValue={a.body} rows={8} required aria-label="Body" />
                <div className="grid gap-2 sm:grid-cols-4">
                  <input className="input" name="exam_year" type="number" placeholder="Exam year checked" defaultValue={a.exam_year ?? ""} aria-label="Exam year" />
                  <input className="input" name="source_name" placeholder="Source" defaultValue={a.source_name} aria-label="Source name" />
                  <input className="input" name="source_url" type="url" placeholder="Bulletin URL" defaultValue={a.source_url ?? ""} aria-label="Source URL" />
                  <input className="input" name="source_document_id" type="number" placeholder="Document # (optional)" defaultValue={a.source_document_id ?? ""} aria-label="Source document id" />
                </div>
                <div className="flex gap-2">
                  <button className="btn-secondary">Save changes</button>
                  <button type="button" className="btn" onClick={() => run(() => api("/api/admin/verify",
                    { method: "POST", json: { entity_type: "info_article", entity_id: a.id, status: "verified" } }), `“${a.title}” verified.`)}>Mark verified</button>
                </div>
              </form>)}
          </li>))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- colleges & nearby places

export function CollegesPanel({ onChange }: { onChange: () => void }) {
  const { run, feedback } = useAction(onChange);
  return (
    <div className="space-y-4">
      {feedback}
      <form className="card grid gap-2 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
        const num = (k: string) => (f.get(k) ? Number(f.get(k)) : null);
        run(() => api<{ id: number }>("/api/admin/colleges", { method: "POST", json: {
          code: f.get("code"), name: f.get("name"), state: f.get("state"), city: f.get("city") || null, institution_type: f.get("institution_type"),
          website: f.get("website") || null, latitude: num("latitude"), longitude: num("longitude"),
          aliases: String(f.get("aliases") || "").split(";").map((s) => s.trim()).filter(Boolean),
          source_name: f.get("source_name"), source_url: f.get("source_url") || null } }),
          (r) => `College #${(r as { id: number }).id} created (unverified).`).then((ok) => ok && form.reset()); }}>
        <h2 className="h2 sm:col-span-3">Add a real college</h2>
        <p className="text-xs text-slate-500 sm:col-span-3">Use the official name and the code your counselling data uses. Add every spelling used in allotment lists as an alias (separate with ;) so imports can match it.</p>
        <input className="input" name="code" required placeholder="Stable code" />
        <input className="input sm:col-span-2" name="name" required placeholder="Official name" />
        <input className="input" name="state" required placeholder="State" />
        <input className="input" name="city" placeholder="City" />
        <select className="input" name="institution_type" aria-label="Institution type"><option>government</option><option>private</option><option>deemed</option><option>central</option><option>aiims</option><option>esic</option><option>afmc</option></select>
        <input className="input" name="latitude" type="number" step="any" placeholder="Latitude (verified)" />
        <input className="input" name="longitude" type="number" step="any" placeholder="Longitude (verified)" />
        <input className="input" name="website" type="url" placeholder="Official website" />
        <input className="input sm:col-span-3" name="aliases" placeholder="Aliases; separated; by semicolons" />
        <input className="input" name="source_name" required minLength={3} placeholder="Source, e.g. NMC college list" />
        <input className="input sm:col-span-2" name="source_url" type="url" placeholder="Source URL" />
        <button className="btn sm:col-span-3">Add college</button>
      </form>
      <form className="card flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); const id = new FormData(e.currentTarget).get("cid");
        run(() => api<{ places: number }>(`/api/admin/colleges/${id}/nearby/refresh`, { method: "POST" }), (r) => `Saved ${(r as { places: number }).places} nearby place(s).`); }}>
        <div className="flex-1"><h2 className="h2">Refresh nearby places</h2>
          <p className="text-xs text-slate-500">Fetches transport, pharmacies, hospitals, banks and shops around the college&apos;s coordinates from OpenStreetMap (needs PLACES_PROVIDER=overpass). Demo colleges are skipped.</p></div>
        <input className="input !w-32" name="cid" type="number" required placeholder="College #" aria-label="College id" />
        <button className="btn">Refresh</button>
      </form>
    </div>
  );
}
