export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** CSRF token set by the API as a readable cookie; echoed on every unsafe request. */
export function csrfHeader(method = "GET"): Record<string, string> {
  if (["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase()) || typeof document === "undefined") return {};
  const m = document.cookie.match(/(?:^|; )neet_csrf=([^;]+)/);
  return m ? { "X-CSRF-Token": decodeURIComponent(m[1]) } : {};
}

const WAKING = [502, 503, 504];

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const safe = ["GET", "HEAD"].includes((rest.method ?? "GET").toUpperCase());
  let res: Response;
  // A free-tier API sleeps when idle and answers 502–504 while it wakes (up to about a minute). Reads are
  // retried quietly; writes are not repeated automatically, so nothing is ever submitted twice.
  for (let attempt = 0; ; attempt++) {
    res = await fetch(path, {
      credentials: "include",
      ...rest,
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...csrfHeader(rest.method),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
    if (!(safe && WAKING.includes(res.status) && attempt < 6)) break;
    await new Promise((r) => setTimeout(r, 5000));
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (WAKING.includes(res.status) && !data.detail)
      throw new ApiError(res.status, "The server is waking up after a quiet spell. Please try again in a few seconds.");
    throw new ApiError(res.status, data.detail ?? `Request failed (${res.status})`);
  }
  return data as T;
}

export const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "Not available" : `₹${v.toLocaleString("en-IN")}`;

export const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("en-IN"));

export const fmtDate = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";

// ---------------------------------------------------------------- shared types

export type Provenance = {
  source_name: string;
  source_url: string | null;
  publication_date: string | null;
  collected_at: string | null;
  last_verified_at: string | null;
  verification_status: string;
};

export type CollegeCardT = {
  id: number;
  code: string;
  name: string;
  city: string | null;
  state: string;
  institution_type: string;
  is_demo: boolean;
  courses: string[];
  fee_summary: { annual_total_inr: number; academic_year: string; verified: boolean } | null;
  hostel_summary: { on_campus: boolean; verification_status: string } | null;
  verification_status: string;
};

export type HistoryRow = {
  exam_year: number;
  final_round: number;
  final_round_name: string | null;
  first_round_closing_rank: number;
  opening_rank: number | null;
  closing_rank: number;
  source_name: string;
  source_url: string | null;
  verification_status: string;
  last_verified_at: string | null;
};

export type PredictionRow = {
  college_id: number;
  college_name: string;
  city: string | null;
  state: string;
  institution_type: string;
  is_demo: boolean;
  course_code: string;
  counselling_authority: string;
  authority_name: string;
  quota: string;
  seat_type: string;
  category_used: string;
  rank_basis: string;
  student_rank_display: string;
  rank_is_estimated: boolean;
  historical_fit: string;
  confidence: string;
  confidence_reason: string;
  years_considered: number[];
  history: HistoryRow[];
  explanation: string;
  caveats: string[];
  estimated_annual_cost_inr: number | null;
  fee_academic_year: string | null;
  hostel_on_campus: boolean;
};

export type PredictionResult = {
  disclaimer: string;
  method: string;
  caveats: string[];
  counts: Record<string, number>;
  groups: Record<string, PredictionRow[]>;
  excluded: { reason: string; count: number }[];
};

export type Me = {
  id: number;
  email: string;
  role: string;
  is_minor: boolean;
  has_profile: boolean;
  guardian_consent_status: "not_required" | "pending" | "verified" | "declined";
  guardian_email: string | null;
};

export const STATES = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana",
  "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Madhya Pradesh",
  "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan",
  "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep",
];

export const CATEGORIES = ["OPEN", "EWS", "OBC", "SC", "ST"];
