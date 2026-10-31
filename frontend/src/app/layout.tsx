import type { Metadata } from "next";
import Link from "next/link";
import { Plus_Jakarta_Sans } from "next/font/google";
import { CompassCross } from "@/components/icons";
import { MascotLauncher } from "@/components/Mascot";
import Nav from "@/components/Nav";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NEET Compass — NEET-UG guidance",
  description: "Source-backed NEET-UG guidance: college matches from historical cutoffs, costs, mock-test tracking and counselling help.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={jakarta.variable}>
      <body className="antialiased">
        <Nav />
        <main className="mx-auto min-h-[70vh] w-full max-w-6xl px-4 py-6 sm:py-9">{children}</main>
        <footer className="relative mt-16 border-t border-slate-200/80 bg-white/70">
          <div aria-hidden="true" className="med-pattern pointer-events-none absolute inset-0 opacity-60 [mask-image:linear-gradient(to_bottom,black,transparent_75%)]" />
          <div className="relative mx-auto max-w-6xl px-4 py-10 pb-24 text-xs leading-relaxed text-slate-500 sm:pr-48">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-teal-500 to-indigo-600 text-white shadow-md shadow-teal-900/20">
                  <CompassCross className="h-4 w-4" />
                </span>
                <p className="font-display text-sm font-extrabold tracking-tight text-slate-800">
                  NEET <span className="text-teal-700">Compass</span>
                </p>
                <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-bold text-teal-700 ring-1 ring-teal-100">
                  NEET-UG → MBBS / BDS
                </span>
              </div>
              <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-1 font-semibold text-slate-600">
                <Link className="hover:text-teal-700" href="/colleges">Colleges</Link>
                <Link className="hover:text-teal-700" href="/predictor">Predictor</Link>
                <Link className="hover:text-teal-700" href="/practice">Practice tests</Link>
                <Link className="hover:text-teal-700" href="/assistant">Assistant</Link>
              </nav>
            </div>
            <p className="mt-5 max-w-3xl">
              NEET Compass gives guidance, not guarantees. College matches are based on past counselling data and cannot
              predict this year&apos;s outcome. Always confirm details with the official sources: NTA (NEET-UG), MCC,
              NMC and your state counselling authority.
            </p>
            <p className="mt-2">Records marked <strong>DEMO</strong> are synthetic development data and are not real colleges or cutoffs.</p>
          </div>
        </footer>
        <MascotLauncher />
      </body>
    </html>
  );
}
