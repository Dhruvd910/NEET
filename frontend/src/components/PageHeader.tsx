import { PulseRule } from "@/components/icons";

// No "use client": server-rendered pages (NEET info, careers) can pass an icon component directly.

/**
 * Page title styled like a hospital department sign: icon tile, department label, title and an ECG rule.
 * `icon` is a medical icon component; `eyebrow` is the small label above the title.
 */
export function PageHeader({ title, children, icon: Icon, eyebrow }: {
  title: string; children?: React.ReactNode; icon?: (p: { className?: string }) => React.ReactElement; eyebrow?: string;
}) {
  return (
    <header className="relative mb-6 overflow-hidden">
      {Icon && (
        <Icon aria-hidden="true" className="pointer-events-none absolute -top-4 right-0 hidden h-36 w-36 text-teal-600/[0.06] sm:block" />)}
      <div className="flex items-start gap-3.5">
        {Icon && (
          <span className="mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-600 text-white shadow-lg shadow-teal-900/15">
            <Icon className="h-5 w-5" />
          </span>)}
        <div className="min-w-0">
          {eyebrow && <p className="eyebrow mb-1 text-teal-700">{eyebrow}</p>}
          <h1 className="h1">{title}</h1>
          <PulseRule className="mt-2 h-3 w-28 text-teal-600/60" aria-hidden="true" />
        </div>
      </div>
      {children && <div className="mt-3 max-w-3xl text-slate-600">{children}</div>}
    </header>
  );
}
