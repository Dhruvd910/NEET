"use client";

import { Loading, ErrorBox, Source, useApi } from "@/components/ui";
import type { Provenance } from "@/lib/api";

type Article = Provenance & { slug: string; title: string; body: string; exam_year: number | null };

export default function Articles({ section }: { section: string }) {
  const { data, error, loading } = useApi<Article[]>(`/api/info/${section}`);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="space-y-3">
      {data?.map((a) => (
        <details key={a.slug} className="card group" open={data.length <= 2}>
          <summary className="cursor-pointer list-none font-semibold text-slate-900">
            <span className="mr-2 inline-block transition group-open:rotate-90">›</span>{a.title}
            {a.exam_year && <span className="ml-2 text-xs font-normal text-slate-500">NEET {a.exam_year}</span>}
          </summary>
          <div className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-700">{a.body}</div>
          <Source p={a} className="mt-3" />
        </details>
      ))}
    </div>
  );
}
