"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CompassCross } from "@/components/icons";
import { api, type Me } from "@/lib/api";

const LINKS = [
  ["/dashboard", "Dashboard"],
  ["/predictor", "Predictor"],
  ["/colleges", "Colleges"],
  ["/compare", "Compare"],
  ["/practice", "Practice"],
  ["/study-plan", "Study plan"],
  ["/assistant", "Assistant"],
] as const;

const MORE = [
  ["/mock-tests", "Mock log"],
  ["/counselling", "Counselling"],
  ["/neet", "NEET info"],
  ["/careers", "Careers"],
] as const;

function Logo() {
  return (
    <Link href="/" className="group flex shrink-0 items-center gap-2.5" aria-label="NEET Compass home">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-400 via-teal-600 to-indigo-600 text-white shadow-lg shadow-teal-900/25 ring-1 ring-white/40 transition group-hover:scale-105">
        <CompassCross className="h-5 w-5" />
      </span>
      <span className="hidden font-display text-[13px] font-extrabold tracking-tight whitespace-nowrap text-slate-900 min-[380px]:inline sm:text-[15px]">
        NEET <span className="bg-gradient-to-r from-teal-600 to-indigo-600 bg-clip-text text-transparent">Compass</span>
        <span className="ml-1.5 hidden rounded bg-teal-50 px-1.5 py-0.5 text-[9px] font-bold tracking-wide text-teal-700 ring-1 ring-teal-100 align-middle xl:inline">
          MBBS / BDS
        </span>
      </span>
    </Link>
  );
}

function ConsentBanner({ me }: { me: Me }) {
  const [sent, setSent] = useState<string | null>(null);
  if (me.guardian_consent_status === "declined")
    return (
      <p role="status" className="bg-red-50 px-4 py-2 text-center text-sm text-red-900">
        Your parent or guardian did not give consent, so this account can&apos;t store personal data. It will be deleted
        automatically. You can still browse colleges and use the predictor without signing in.
      </p>
    );
  async function deleteAccount() {
    if (!confirm("Permanently delete this account? This cannot be undone.")) return;
    await api("/api/auth/me", { method: "DELETE" });
    window.location.href = "/";
  }
  async function resend() {
    try {
      const r = await api<{ sent_to: string }>("/api/auth/guardian-consent-resend", { method: "POST" });
      setSent(`Sent again to ${r.sent_to}.`);
    } catch (e) {
      setSent(e instanceof Error ? e.message : "Could not resend.");
    }
  }
  return (
    <p role="status" className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
      Waiting for your parent or guardian ({me.guardian_email}) to give consent. Until then, saving your profile, mock
      tests and chats is switched off.{" "}
      <button className="underline" onClick={resend}>Resend the email</button>
      {" · "}
      <button className="underline" onClick={deleteAccount}>Delete this account</button>
      {sent && <span className="ml-2">{sent}</span>}
    </p>
  );
}

export default function Nav() {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [more, setMore] = useState(false);

  useEffect(() => {
    api<Me>("/api/auth/me").then(setMe).catch(() => setMe(null));
  }, [path]);
  useEffect(() => { setOpen(false); setMore(false); }, [path]);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    setMe(null);
    router.push("/");
  }

  const link = (href: string, label: string) => {
    const active = path === href || path.startsWith(`${href}/`);
    return (
      <Link
        key={href}
        href={href}
        aria-current={active ? "page" : undefined}
        className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[13px] transition ${
          active
            ? "bg-gradient-to-r from-teal-50 to-emerald-50 font-bold text-teal-800 ring-1 ring-teal-100"
            : "font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`}
      >
        {label}
      </Link>
    );
  };

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/80 backdrop-blur-xl">
      <nav className="mx-auto flex max-w-6xl items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-4" aria-label="Main">
        <Logo />
        <div className="mx-2 hidden flex-1 items-center gap-0.5 lg:flex">
          {LINKS.map(([h, l]) => link(h, l))}
          <div className="relative">
            <button
              type="button"
              onClick={() => setMore((v) => !v)}
              aria-expanded={more}
              aria-haspopup="menu"
              className={`inline-flex items-center gap-1 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition ${
                more || MORE.some(([h]) => path.startsWith(h))
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              More
              <svg viewBox="0 0 24 24" className={`h-3.5 w-3.5 transition ${more ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {more && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setMore(false)} aria-hidden="true" />
                <div role="menu" className="absolute left-0 z-40 mt-2 w-48 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/10">
                  {MORE.map(([h, l]) => (
                    <Link
                      key={h}
                      href={h}
                      role="menuitem"
                      className={`block rounded-lg px-3 py-2 text-[13px] transition ${
                        path.startsWith(h) ? "bg-teal-50 font-bold text-teal-800" : "font-medium text-slate-700 hover:bg-slate-100"
                      }`}
                    >
                      {l}
                    </Link>
                  ))}
                  {me?.role === "admin" && (
                    <Link href="/admin" role="menuitem" className="block rounded-lg px-3 py-2 text-[13px] font-medium text-slate-700 hover:bg-slate-100">
                      Admin
                    </Link>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {me ? (
            <>
              <Link href="/profile" className="hidden text-[13px] font-semibold text-slate-600 hover:text-teal-700 sm:inline">
                Profile
              </Link>
              <button onClick={logout} className="btn-secondary !rounded-lg !px-3 !py-1.5 !text-[13px]">Sign out</button>
            </>
          ) : (
            <>
              <Link href="/login" className="btn-secondary hidden !rounded-lg !px-3 !py-1.5 !text-[13px] sm:inline-flex">Sign in</Link>
              <Link href="/register" className="btn !rounded-lg !px-3 !py-1.5 !text-[13px]">Get started</Link>
            </>
          )}
          <button
            className="btn-secondary !rounded-lg !px-2.5 !py-1.5 lg:hidden"
            aria-expanded={open}
            aria-label="Menu"
            onClick={() => setOpen(!open)}
          >
            ☰
          </button>
        </div>
      </nav>
      {me && me.is_minor && me.guardian_consent_status !== "verified" && <ConsentBanner me={me} />}
      {open && (
        <div className="border-t border-slate-200/70 bg-white px-3 py-3 lg:hidden" onClick={() => setOpen(false)}>
          <div className="grid grid-cols-2 gap-1">
            {[...LINKS, ...MORE].map(([h, l]) => link(h, l))}
            {me && link("/profile", "Profile")}
            {me?.role === "admin" && link("/admin", "Admin")}
          </div>
          {!me && (
            <Link href="/login" className="btn-secondary mt-2.5 w-full">Sign in</Link>
          )}
        </div>
      )}
    </header>
  );
}
