"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Atom, Dna, Flask, Leaf, Stethoscope } from "@/components/icons";
export { PageHeader } from "@/components/PageHeader";
import { api, ApiError, fmtDate, inr, type CollegeCardT, type Provenance } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  verified: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  demo: "bg-amber-50 text-amber-900 ring-amber-300",
  unverified: "bg-slate-100 text-slate-700 ring-slate-300",
  pending_review: "bg-sky-50 text-sky-800 ring-sky-200",
  outdated: "bg-orange-50 text-orange-800 ring-orange-200",
  conflicting: "bg-red-50 text-red-800 ring-red-200",
};
const STATUS_LABEL: Record<string, string> = {
  verified: "Verified",
  demo: "DEMO data — not real",
  unverified: "Unverified",
  pending_review: "Pending verification",
  outdated: "Outdated",
  conflicting: "Conflicting sources",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${STATUS_STYLE[status] ?? STATUS_STYLE.unverified}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function FitBadge({ fit }: { fit: string }) {
  const style =
    fit === "Stronger historical fit" ? "bg-teal-50 text-teal-800 ring-teal-200"
      : fit === "Possible / uncertain" ? "bg-indigo-50 text-indigo-800 ring-indigo-200"
        : "bg-rose-50 text-rose-800 ring-rose-200";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${style}`}>{fit}</span>;
}

export function Source({ p, className = "" }: { p: Partial<Provenance>; className?: string }) {
  return (
    <p className={`text-xs text-slate-500 ${className}`}>
      Source:{" "}
      {p.source_url ? (
        <a className="underline" href={p.source_url} target="_blank" rel="noreferrer">{p.source_name}</a>
      ) : (
        p.source_name ?? "unknown"
      )}
      {p.publication_date && <> · published {fmtDate(p.publication_date)}</>}
      {" · "}last verified {p.last_verified_at ? fmtDate(p.last_verified_at) : "never"}{" "}
      {p.verification_status && <StatusBadge status={p.verification_status} />}
    </p>
  );
}

export function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warn" }) {
  const cls = tone === "warn" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-sky-200 bg-sky-50 text-sky-900";
  return <div role="note" className={`rounded-lg border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

/** Heartbeat trace while data loads. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-sm text-slate-500" role="status" aria-live="polite">
      <svg viewBox="0 0 120 24" className="h-6 w-28 text-teal-600" aria-hidden="true">
        <path d="M0 12h30l4-8 6 16 5-12 4 4h20l4-8 6 16 5-12 4 4h32" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" className="ecg-trace" />
      </svg>
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{msg}</div>;
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center">
      <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-full bg-teal-50 text-teal-700 ring-1 ring-teal-100">
        <Stethoscope className="h-5 w-5" />
      </span>
      <p className="font-medium text-slate-800">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

/** Small data hook: GET on mount, exposes reload. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(!!path);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [path, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

export function SignInPrompt({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 403 && error.message.includes("guardian"))
    return <Empty title="Waiting for your parent or guardian">{error.message}</Empty>;
  if (error instanceof ApiError && error.status === 401)
    return (
      <Empty title="Please sign in to use this page">
        <Link className="text-teal-700 underline" href="/login">Sign in</Link> or{" "}
        <Link className="text-teal-700 underline" href="/register">create an account</Link>.
      </Empty>
    );
  return <ErrorBox error={error} />;
}

export function CollegeCard({ c, extra, onCompare, saved, onSave }: {
  c: CollegeCardT;
  extra?: React.ReactNode;
  onCompare?: () => void;
  saved?: boolean;
  onSave?: () => void;
}) {
  return (
    <article className="card flex flex-col gap-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link href={`/colleges/${c.id}`} className="font-semibold text-slate-900 hover:text-teal-700">{c.name}</Link>
          <p className="text-sm text-slate-600">
            {[c.city, c.state].filter(Boolean).join(", ")} · <span className="capitalize">{c.institution_type}</span>
            {c.courses.length > 0 && <> · {c.courses.join(", ")}</>}
          </p>
        </div>
        {c.is_demo && <StatusBadge status="demo" />}
      </div>
      {extra}
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-slate-500">Est. annual cost</dt>
          <dd className="font-medium">
            {c.fee_summary ? <>{inr(c.fee_summary.annual_total_inr)} <span className="text-xs text-slate-500">({c.fee_summary.academic_year}{c.fee_summary.verified ? ", verified" : ", not verified"})</span></> : "Not available"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Campus hostel</dt>
          <dd className="font-medium">{c.hostel_summary ? "Listed" : "No verified info"}</dd>
        </div>
      </dl>
      <div className="mt-1 flex flex-wrap gap-2">
        <Link className="btn-secondary" href={`/colleges/${c.id}`}>Full details</Link>
        {onSave && <button className="btn-secondary" onClick={onSave}>{saved ? "★ Saved" : "☆ Save"}</button>}
        {onCompare && <button className="btn-secondary" onClick={onCompare}>+ Compare</button>}
      </div>
    </article>
  );
}

export const SUBJECT_STYLE: Record<string, { icon: (p: { className?: string }) => React.ReactElement; tint: string; soft: string }> = {
  Physics: { icon: Atom, tint: "from-sky-500 to-blue-600", soft: "bg-sky-50 text-sky-800 ring-sky-200" },
  Chemistry: { icon: Flask, tint: "from-amber-500 to-orange-600", soft: "bg-amber-50 text-amber-900 ring-amber-200" },
  Botany: { icon: Leaf, tint: "from-emerald-500 to-teal-600", soft: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
  Zoology: { icon: Dna, tint: "from-violet-500 to-purple-600", soft: "bg-violet-50 text-violet-800 ring-violet-200" },
  Biology: { icon: Dna, tint: "from-emerald-500 to-violet-600", soft: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
};

/** Small coloured subject label with its icon (atom, flask, leaf, DNA). */
export function SubjectBadge({ subject, className = "" }: { subject: string; className?: string }) {
  const st = SUBJECT_STYLE[subject];
  if (!st) return <span className={className}>{subject}</span>;
  const Icon = st.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${st.soft} ${className}`}>
      <Icon className="h-3.5 w-3.5" />{subject}
    </span>
  );
}

/** Compare tray stored per-browser (convenience only). */
export function getCompareIds(): number[] {
  try { return JSON.parse(localStorage.getItem("compare") ?? "[]"); } catch { return []; }
}
export function toggleCompare(id: number): number[] {
  const ids = getCompareIds();
  const next = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id].slice(-5);
  try { localStorage.setItem("compare", JSON.stringify(next)); } catch { /* storage unavailable */ }
  return next;
}

const noopSubscribe = () => () => {};
/** False during server rendering and before hydration. Forms with secrets stay disabled until JS runs,
 *  so an early click can never fall back to a native GET submit that puts passwords in the URL. */
export function useHydrated() {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}
