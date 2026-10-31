"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Scale } from "@/components/icons";
import { Empty, ErrorBox, Loading, Notice, PageHeader, StatusBadge, getCompareIds, toggleCompare, useApi } from "@/components/ui";
import { api, inr, num } from "@/lib/api";

type Row = { id: number; name: string; city: string | null; state: string; institution_type: string; is_demo: boolean;
  recognition_status: string | null; counselling_routes: string[]; aiq_open_closing: { exam_year: number; closing_rank: number } | null;
  annual_cost_inr: number | null; full_course_cost_inr: number | null; fee_year: string | null; hostel_mess_annual_inr: number | null;
  hostel_on_campus: boolean; hospital_beds: number | null; internship_stipend_monthly_inr: number | null; avg_rating: number | null;
  review_count: number; nearest_railway_km: number | null; nearest_airport_km: number | null; nearby_pg_count: number;
  last_verified_at: string | null; data_status: string; completeness: number; intake: Record<string, number> };
type Result = { colleges: Row[]; insights: string[]; note: string; any_demo: boolean; priorities: string[] };

const ROWS: [string, (r: Row) => React.ReactNode][] = [
  ["Location", (r) => `${r.city ?? ""}, ${r.state}`],
  ["Type", (r) => <span className="capitalize">{r.institution_type}</span>],
  ["Approved MBBS intake", (r) => Object.entries(r.intake).map(([y, n]) => `${n} (${y})`).join(", ") || "—"],
  ["Counselling routes", (r) => r.counselling_routes.join(", ") || "—"],
  ["AIQ OPEN closing rank (latest)", (r) => r.aiq_open_closing ? `${num(r.aiq_open_closing.closing_rank)} (${r.aiq_open_closing.exam_year})` : "No AIQ data"],
  ["Estimated yearly cost", (r) => <>{inr(r.annual_cost_inr)} {r.fee_year && <span className="text-xs text-slate-500">({r.fee_year})</span>}</>],
  ["Estimated full course", (r) => inr(r.full_course_cost_inr)],
  ["Hostel + mess / year", (r) => inr(r.hostel_mess_annual_inr)],
  ["Campus hostel", (r) => (r.hostel_on_campus ? "Listed" : "No verified info")],
  ["Hospital beds", (r) => num(r.hospital_beds)],
  ["Internship stipend / month", (r) => inr(r.internship_stipend_monthly_inr)],
  ["Student rating", (r) => (r.avg_rating ? `${r.avg_rating}/5 (${r.review_count})` : "No reviews")],
  ["Nearest railway / airport", (r) => `${r.nearest_railway_km ?? "—"} km / ${r.nearest_airport_km ?? "—"} km`],
  ["Nearby PGs listed", (r) => r.nearby_pg_count],
  ["Recognition", (r) => r.recognition_status ?? "Not verified"],
  ["Data status", (r) => <StatusBadge status={r.data_status} />],
  ["Data completeness", (r) => `${Math.round(r.completeness * 100)}%`],
];

export default function ComparePage() {
  const prios = useApi<Record<string, string>>("/api/compare/priorities");
  const [ids, setIds] = useState<number[]>([]);
  const [chosen, setChosen] = useState<string[]>(["cost", "cutoff", "hostel"]);
  const [res, setRes] = useState<Result | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setIds(getCompareIds()); }, []);
  useEffect(() => {
    if (ids.length < 2) { setRes(null); return; }
    setLoading(true);
    api<Result>("/api/compare", { method: "POST", json: { college_ids: ids, priorities: chosen } })
      .then((r) => { setRes(r); setError(null); }).catch(setError).finally(() => setLoading(false));
  }, [ids, chosen]);

  return (
    <div className="space-y-5">
      <PageHeader icon={Scale} eyebrow="Side by side" title="Compare colleges">Choose what matters to you. We explain who leads on each of <em>your</em> criteria — there is no universal &quot;best&quot; college.</PageHeader>
      {ids.length < 2 ? (
        <Empty title="Add at least two colleges to compare">Use “+ Compare” on the <Link className="text-teal-700 underline" href="/colleges">college list</Link> or in predictor results (up to 5).</Empty>
      ) : (<>
        <fieldset className="card">
          <legend className="label">Your priorities</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">{prios.data && Object.entries(prios.data).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={chosen.includes(k)}
              onChange={() => setChosen(chosen.includes(k) ? chosen.filter((x) => x !== k) : [...chosen, k])} />{label}</label>))}</div>
        </fieldset>
        <ErrorBox error={error} />
        {loading && !res && <Loading />}
        {res && (<>
          {res.any_demo && <Notice tone="warn">Includes DEMO colleges — figures are synthetic.</Notice>}
          <section className="card">
            <h2 className="h2">What stands out for your priorities</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{res.insights.map((i) => <li key={i}>{i}</li>)}</ul>
            <p className="mt-2 text-xs text-slate-500">{res.note}</p>
          </section>
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead><tr className="bg-slate-50"><th className="p-3 text-xs text-slate-500">Criterion</th>{res.colleges.map((c) => (
                <th key={c.id} className="p-3 align-top"><Link className="hover:text-teal-700" href={`/colleges/${c.id}`}>{c.name}</Link>
                  <button className="mt-1 block text-xs font-normal text-red-700 underline" onClick={() => setIds(toggleCompare(c.id))}>Remove</button></th>))}</tr></thead>
              <tbody>{ROWS.map(([label, f]) => (
                <tr key={label} className="border-t border-slate-100"><th className="p-3 text-xs font-medium text-slate-500">{label}</th>{res.colleges.map((c) => <td key={c.id} className="p-3">{f(c)}</td>)}</tr>))}</tbody>
            </table>
          </div>
        </>)}
      </>)}
    </div>
  );
}
