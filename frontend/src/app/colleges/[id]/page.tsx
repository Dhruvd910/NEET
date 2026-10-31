"use client";

import { use, useMemo, useState } from "react";
import { Hospital } from "@/components/icons";
import { ErrorBox, Loading, Notice, PageHeader, Source, StatusBadge, toggleCompare, useApi } from "@/components/ui";
import NearbyPanel, { type Place } from "@/components/NearbyPanel";
import { api, inr, num, type Provenance } from "@/lib/api";

type P = Provenance;
type Detail = {
  overview: P & { id: number; name: string; aliases: string[]; website: string | null; address: string | null; city: string | null;
    state: string; institution_type: string; university: string | null; established_year: number | null; recognition_status: string | null;
    recognition_year: string | null; is_demo: boolean;
    latitude: number | null; longitude: number | null;
    courses: Record<string, (P & { course: string; academic_year: string; approved_intake: number | null; duration_years: number; duration_note: string | null })[]> };
  admission: { counselling_authorities: string[];
    cutoffs: (P & { course: string; authority: string; exam_year: number; round: number; round_name: string | null; quota: string; category: string;
      seat_type: string; rank_basis: string; domicile_required: boolean; opening_rank: number | null; closing_rank: number })[] };
  costs: Record<string, { available: boolean; academic_year: string | null; annual_mandatory_inr: number; annual_hostel_mess_inr: number;
    one_time_inr: number; refundable_deposits_inr: number; estimated_annual_total_inr: number; estimated_full_course_inr: number;
    course_duration_years: number | null; warnings: string[];
    fee_lines: { fee_type: string; amount_inr: number; period: string; mandatory: boolean; refundable: boolean; academic_year: string;
      source_name: string; source_url: string | null; verification_status: string; note: string | null }[] }>;
  hostels: (P & { on_campus: boolean; provider_name: string | null; gender: string | null; hostel_count: number | null; capacity: number | null;
    room_types: string[]; facilities: string[]; rules_note: string | null; rent_min_inr: number | null; rent_max_inr: number | null;
    rent_period: string | null; distance_km: number | null; availability_note: string })[];
  facilities: (P & { category: string; name: string; details: string | null; numeric_value: number | null; unit: string | null })[];
  outcomes: (P & { metric: string; value_text: string | null; value_numeric: number | null; year: string | null; comparable: boolean })[];
  nearby: Place[];
  reviews: { label: string; count: number; average_rating: number | null;
    items: { rating: number; aspect_ratings: Record<string, number>; body: string; is_demo: boolean; created_at: string }[] };
};

const TABS = ["Overview", "Admission", "Fees & cost", "Hostel", "Academics", "Outcomes", "Campus life", "Around campus"] as const;
export default function CollegePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: d, error, loading } = useApi<Detail>(`/api/colleges/${id}`);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");

  if (loading) return <Loading />;
  if (error || !d) return <ErrorBox error={error ?? "College not found"} />;
  const o = d.overview;

  return (
    <div className="space-y-5">
      <PageHeader icon={Hospital} eyebrow="Medical college" title={o.name}>
        <p>{[o.city, o.state].filter(Boolean).join(", ")} · <span className="capitalize">{o.institution_type}</span>{o.university && ` · ${o.university}`}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => api(`/api/saved-colleges/${o.id}`, { method: "POST" }).then(() => alert("Saved to your shortlist.")).catch(() => alert("Sign in to save colleges."))}>☆ Save</button>
          <button className="btn-secondary" onClick={() => { toggleCompare(o.id); alert("Added to compare list."); }}>+ Compare</button>
        </div>
      </PageHeader>
      {o.is_demo && <Notice tone="warn"><strong>DEMO college.</strong> This is a fictional record used to develop the platform. None of its figures are real.</Notice>}

      <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === t ? "border-teal-700 font-medium text-teal-800" : "border-transparent text-slate-600 hover:text-slate-900"}`}>{t}</button>
        ))}
      </div>

      {tab === "Overview" && (
        <section className="card space-y-3">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <Row k="Official website" v={o.website ? <a className="underline" href={o.website} target="_blank" rel="noreferrer">{o.website}</a> : "Not available"} />
            <Row k="Address" v={o.address ?? "Not available"} />
            <Row k="Established" v={o.established_year ?? "Not available"} />
            <Row k="Recognition" v={o.recognition_status ? `${o.recognition_status} (${o.recognition_year})` : "Not verified"} />
            <Row k="Also known as" v={o.aliases.join("; ") || "—"} />
          </dl>
          <h2 className="h2">Courses & approved intake</h2>
          {Object.entries(o.courses).map(([code, rows]) => rows.map((c) => (
            <div key={code + c.academic_year} className="text-sm">
              <p><strong>{code}</strong> — {c.course}: {c.approved_intake ?? "?"} seats ({c.academic_year}) · {c.duration_years} years{c.duration_note && ` (${c.duration_note})`}</p>
              <Source p={c} />
            </div>)))}
          <Source p={o} />
        </section>
      )}

      {tab === "Admission" && <Admission d={d} />}
      {tab === "Fees & cost" && <Costs d={d} />}

      {tab === "Hostel" && (
        <section className="space-y-3">
          {d.hostels.length === 0 && <p className="card">No verified hostel information. Contact the college directly.</p>}
          {d.hostels.map((h, i) => (
            <div key={i} className="card text-sm">
              <h3 className="font-medium">{h.on_campus ? `Campus hostel — ${h.gender ?? "all"}` : h.provider_name ?? "Off-campus accommodation"}</h3>
              <dl className="mt-2 grid gap-2 sm:grid-cols-3">
                {h.on_campus ? (<>
                  <Row k="Hostels" v={h.hostel_count ?? "Not published"} /><Row k="Capacity" v={h.capacity ?? "Not published"} />
                  <Row k="Rooms" v={h.room_types.join(", ") || "Not published"} />
                </>) : (<>
                  <Row k="Rent" v={h.rent_min_inr ? `${inr(h.rent_min_inr)}–${inr(h.rent_max_inr)} / ${h.rent_period}` : "Not available"} />
                  <Row k="Distance" v={h.distance_km != null ? `${h.distance_km} km` : "—"} />
                </>)}
                <Row k="Facilities" v={h.facilities.join(", ") || "—"} />
              </dl>
              <p className="mt-2 text-amber-800">{h.availability_note}</p>
              <Source p={h} className="mt-1" />
            </div>
          ))}
        </section>
      )}

      {tab === "Academics" && (
        <section className="card space-y-3 text-sm">
          {d.facilities.length === 0 && <p>No verified academic or clinical facility data yet.</p>}
          {d.facilities.map((f, i) => (
            <div key={i}><p><span className="capitalize text-slate-500">{f.category}:</span> <strong>{f.name}</strong>
              {f.numeric_value != null && ` — ${num(f.numeric_value)} ${f.unit ?? ""}`}{f.details && ` · ${f.details}`}</p><Source p={f} /></div>
          ))}
        </section>
      )}

      {tab === "Outcomes" && (
        <section className="card space-y-3 text-sm">
          <Notice>Medical colleges don&apos;t have &quot;placements&quot; in the engineering sense. We show internship, stipend and postgraduate pathway information only when it is sourced, and flag figures that cannot be compared across colleges.</Notice>
          {d.outcomes.map((x, i) => (
            <div key={i}><p><strong>{x.metric.replaceAll("_", " ")}</strong>: {x.value_numeric != null ? inr(x.value_numeric) : x.value_text} {x.year && `(${x.year})`}
              {!x.comparable && <span className="ml-1 text-xs text-slate-500">· not comparable across colleges</span>}</p><Source p={x} /></div>
          ))}
        </section>
      )}

      {tab === "Campus life" && (
        <section className="card space-y-3 text-sm">
          <p className="text-slate-600">{d.reviews.label}</p>
          <p>{d.reviews.count ? <>Average student rating <strong>{d.reviews.average_rating}/5</strong> from {d.reviews.count} review(s)</> : "No approved reviews yet."}</p>
          {d.reviews.items.map((r, i) => (
            <blockquote key={i} className="rounded-lg bg-slate-50 p-3">
              <p>{"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)} {r.is_demo && <StatusBadge status="demo" />}</p>
              <p className="mt-1">{r.body}</p>
            </blockquote>
          ))}
          <ReviewForm collegeId={o.id} />
        </section>
      )}

      {tab === "Around campus" && (
        <NearbyPanel places={d.nearby} lat={o.latitude} lon={o.longitude} collegeName={o.name} isDemo={o.is_demo} />
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div><dt className="text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>;
}

function Admission({ d }: { d: Detail }) {
  const groups = useMemo(() => [...new Set(d.admission.cutoffs.map((c) => `${c.course} · ${c.authority} · ${c.quota}`))], [d]);
  const [g, setG] = useState(groups[0] ?? "");
  const [cat, setCat] = useState("OPEN");
  const rows = d.admission.cutoffs.filter((c) => `${c.course} · ${c.authority} · ${c.quota}` === g && c.category === cat);
  const cats = [...new Set(d.admission.cutoffs.filter((c) => `${c.course} · ${c.authority} · ${c.quota}` === g).map((c) => c.category))];
  return (
    <section className="card space-y-3 text-sm">
      <p>Entrance exam: <strong>NEET-UG</strong> · Counselling: {d.admission.counselling_authorities.join(", ") || "—"}</p>
      {groups.length === 0 ? <p>No cutoff data yet.</p> : (<>
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-2">Route <select className="input !w-auto" value={g} onChange={(e) => setG(e.target.value)}>{groups.map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="flex items-center gap-2">Category <select className="input !w-auto" value={cat} onChange={(e) => setCat(e.target.value)}>{cats.map((x) => <option key={x}>{x}</option>)}</select></label>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left">
            <thead className="text-xs text-slate-500"><tr><th className="py-1">Year</th><th>Round</th><th>Opening</th><th>Closing</th><th>Basis</th><th>Domicile</th><th>Status</th></tr></thead>
            <tbody>{rows.map((c, i) => (
              <tr key={i} className="border-t border-slate-100"><td className="py-1">{c.exam_year}</td><td>{c.round_name ?? c.round}</td><td>{num(c.opening_rank)}</td>
                <td className="font-medium">{num(c.closing_rank)}</td><td>{c.rank_basis === "AIR" ? "AIR" : "State rank"}</td><td>{c.domicile_required ? "Required" : "No"}</td>
                <td><StatusBadge status={c.verification_status} /></td></tr>))}</tbody>
          </table>
        </div>
        {rows[0] && <Source p={rows[0]} />}
        <p className="text-xs text-slate-500">Cutoffs from different routes, categories or years are not interchangeable. Past cutoffs do not predict this year&apos;s.</p>
      </>)}
    </section>
  );
}

function Costs({ d }: { d: Detail }) {
  const entries = Object.entries(d.costs);
  if (!entries.length) return <p className="card">No fee information yet.</p>;
  return (
    <section className="space-y-4">
      {entries.map(([code, c]) => (
        <div key={code} className="card space-y-3 text-sm">
          <h2 className="h2">{code} — estimated cost {c.academic_year && <span className="text-sm font-normal text-slate-500">(fees for {c.academic_year})</span>}</h2>
          {!c.available ? <p>No fee records available.</p> : (<>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Estimated per year" value={inr(c.estimated_annual_total_inr)} hint="Mandatory fees + hostel & mess" />
              <Stat label="One-time charges" value={inr(c.one_time_inr)} hint={`+ ${inr(c.refundable_deposits_inr)} refundable deposit`} />
              <Stat label="Full course (estimate)" value={inr(c.estimated_full_course_inr)} hint={`${c.course_duration_years ?? "?"} year course`} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left">
                <thead className="text-xs text-slate-500"><tr><th className="py-1">Fee</th><th>Amount</th><th>Period</th><th>Type</th><th>Source</th></tr></thead>
                <tbody>{c.fee_lines.map((l) => (
                  <tr key={l.fee_type} className="border-t border-slate-100"><td className="py-1 capitalize">{l.fee_type.replace("_", " ")}</td><td>{inr(l.amount_inr)}</td>
                    <td>{l.period.replace("_", " ")}</td><td>{l.mandatory ? "Mandatory" : "Optional"}{l.refundable && " · refundable"}</td>
                    <td className="text-xs">{l.source_name} <StatusBadge status={l.verification_status} /></td></tr>))}</tbody>
              </table>
            </div>
          </>)}
          <ul className="list-disc pl-5 text-xs text-amber-800">{c.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      ))}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="text-lg font-semibold">{value}</p>{hint && <p className="text-xs text-slate-500">{hint}</p>}</div>;
}

function ReviewForm({ collegeId }: { collegeId: number }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ message: string }>(`/api/colleges/${collegeId}/reviews`, { method: "POST", json: { rating: Number(f.get("rating")), body: f.get("body") } });
      setMsg(r.message); setErr(null);
    } catch (x) { setErr(x); }
  }
  if (msg) return <Notice>{msg}</Notice>;
  return (
    <form onSubmit={submit} className="space-y-2 border-t border-slate-200 pt-3">
      <h3 className="font-medium">Studied here? Share your experience</h3>
      <p className="text-xs text-slate-500">Reviews are moderated. Don&apos;t include names or personal details of anyone.</p>
      <select name="rating" className="input !w-auto" defaultValue="4" aria-label="Rating">{[5, 4, 3, 2, 1].map((r) => <option key={r} value={r}>{r} stars</option>)}</select>
      <textarea name="body" className="input" rows={3} minLength={30} maxLength={3000} required placeholder="Academics, hostel, mess, clinical exposure… (min. 30 characters)" />
      <ErrorBox error={err} />
      <button className="btn">Submit for moderation</button>
    </form>
  );
}
