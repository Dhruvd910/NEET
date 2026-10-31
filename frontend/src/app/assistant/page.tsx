"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  CompassCross,
  MessageSquare,
  Mic,
  PanelLeft,
  Plus,
  Search,
  Send,
  Sparkle,
  Trash,
  Volume,
  X,
} from "@/components/icons";
import Mascot, { MascotAvatar, type MascotState } from "@/components/Mascot";
import { ErrorBox, Loading, SignInPrompt, StatusBadge, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { useListener, useSpeech, useVoiceSupport, VOICE_LANGS } from "@/lib/voice";

type Citation = { source_name: string; url: string | null; year: number | string | null; verification_status: string | null; page: number | null };
type Msg = { id: number; role: "user" | "assistant"; content: string; citations: Citation[]; tool_calls: string[]; created_at?: string | null; spoken?: boolean };
type Chat = { id: number; title: string | null; created_at: string; updated_at: string; message_count: number };

const SUGGESTIONS = [
  { q: "Which colleges might be realistic for my rank?", tag: "Predictor" },
  { q: "How does AIQ differ from state quota?", tag: "Counselling" },
  { q: "What documents should I prepare for counselling?", tag: "Counselling" },
  { q: "What should I improve based on my mock tests?", tag: "Mock tests" },
  { q: "What are alternatives to MBBS?", tag: "Careers" },
];

const MASCOT_LINE: Record<MascotState, string> = {
  idle: "Ask me anything about NEET-UG — cutoffs, colleges, counselling or your own mock scores.",
  listening: "I'm listening…",
  thinking: "Let me look that up…",
  talking: "Here's what I found.",
};

/** The API stores naive UTC timestamps, so read them back as UTC. */
function parseDate(v?: string | null) {
  if (!v) return null;
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(v) ? v : `${v}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const clock = (v?: string | null) => {
  const d = parseDate(v);
  return d ? d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
};
const shortDate = (v?: string | null) => {
  const d = parseDate(v);
  return d ? d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
};
const longStamp = (v?: string | null) => {
  const d = parseDate(v);
  return d ? `${d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" })} · ${clock(v)}` : "";
};

const GROUPS = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"] as const;

function groupFor(v?: string | null): (typeof GROUPS)[number] {
  const d = parseDate(v);
  if (!d) return "Older";
  const midnight = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((midnight(new Date()) - midnight(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  if (days < 30) return "Previous 30 days";
  return "Older";
}

/** Minimal, safe markdown: **bold**, *italic*, bullet lines and line breaks (no HTML injection). */
function Inline({ s }: { s: string }) {
  return (
    <>
      {s.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g).map((part, j) => {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={j}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={j}>{part.slice(1, -1)}</em>;
        return part;
      })}
    </>
  );
}

function Text({ s }: { s: string }) {
  return (
    <>
      {s.split("\n").map((line, i) => {
        if (line.trim() === "") return <span key={i} className="block h-2" />;
        const bullet = /^\s*[-•]\s+/.test(line);
        const body = line.replace(/^\s*[-•]\s+/, "");
        return (
          <p key={i} className={bullet ? "flex gap-2 pl-1" : ""}>
            {bullet && <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />}
            <span><Inline s={body} /></span>
          </p>
        );
      })}
    </>
  );
}

export default function AssistantPage() {
  const me = useApi("/api/auth/me");
  const chats = useApi<Chat[]>("/api/assistant/sessions");

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [lang, setLang] = useState<string>("en-IN");
  const [readAloud, setReadAloud] = useState(true);
  const [handsFree, setHandsFree] = useState(false);
  const [query, setQuery] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const { canListen, canSpeak } = useVoiceSupport();
  const speech = useSpeech();

  const reloadChats = useRef(chats.reload);
  useEffect(() => { reloadChats.current = chats.reload; });

  const send = useCallback(async (text: string, voice = false) => {
    const content = text.trim();
    if (!content || busy) return;
    speech.stop();
    setMsgs((m) => [...m, {
      id: -Date.now(), role: "user", content, citations: [], tool_calls: [],
      created_at: new Date().toISOString(), spoken: voice,
    }]);
    setInput("");
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ session_id: number; message: Msg }>("/api/assistant/messages",
        { method: "POST", json: { session_id: sessionId, content, voice } });
      setSessionId(r.session_id);
      setMsgs((m) => [...m, r.message]);
      reloadChats.current();
      if (voice && readAloud && canSpeak) {
        speech.speak(r.message.content, lang, handsFree ? () => listenerRef.current?.(lang) : undefined);
      }
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  }, [sessionId, busy, readAloud, canSpeak, speech, lang, handsFree]);

  const listener = useListener((text) => send(text, true));
  const listenerRef = useRef<((l: string) => void) | null>(null);
  useEffect(() => { listenerRef.current = listener.start; }, [listener.start]);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);
  useEffect(() => { if (!drawer) setConfirmId(null); }, [drawer]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = (chats.data ?? []).filter((c) => !needle || (c.title ?? "").toLowerCase().includes(needle));
    return GROUPS.map((label) => ({ label, items: list.filter((c) => groupFor(c.updated_at) === label) }))
      .filter((g) => g.items.length > 0);
  }, [chats.data, query]);

  const current = (chats.data ?? []).find((c) => c.id === sessionId) ?? null;

  const openChat = useCallback(async (id: number) => {
    setDrawer(false);
    if (id === sessionId) return;
    setOpening(true);
    setErr(null);
    try {
      const c = await api<{ id: number; title: string | null; created_at: string; messages: Msg[] }>(`/api/assistant/sessions/${id}`);
      setSessionId(c.id);
      setMsgs(c.messages);
    } catch (x) {
      setErr(x);
    } finally {
      setOpening(false);
    }
  }, [sessionId]);

  const newChat = useCallback(() => {
    setSessionId(null);
    setMsgs([]);
    setErr(null);
    setDrawer(false);
    speech.stop();
    box.current?.focus();
  }, [speech]);

  const removeChat = useCallback(async (id: number) => {
    setConfirmId(null);
    try {
      await api(`/api/assistant/sessions/${id}`, { method: "DELETE" });
      if (id === sessionId) { setSessionId(null); setMsgs([]); }
      reloadChats.current();
    } catch (x) { setErr(x); }
  }, [sessionId]);

  if (me.loading) return <Loading />;
  if (me.error) return <SignInPrompt error={me.error} />;

  const mascotState: MascotState = listener.listening ? "listening" : busy ? "thinking" : speech.speaking ? "talking" : "idle";
  const empty = msgs.length === 0 && !opening;

  return (
    <div className="relative h-[calc(100dvh-8.5rem)] min-h-[540px] lg:h-[calc(100dvh-10rem)]">
      {drawer && (
        <button aria-label="Close chat history" onClick={() => setDrawer(false)}
          className="fixed inset-0 z-40 cursor-default bg-slate-900/40 backdrop-blur-[2px] lg:hidden" />
      )}

      <div className="grid h-full min-h-0 gap-4 lg:grid-cols-[288px_minmax(0,1fr)]">
        {/* ------------------------------------------------ history sidebar */}
        <aside
          aria-label="Chat history"
          className={`fixed inset-y-0 left-0 z-50 flex w-[86%] max-w-[320px] flex-col overflow-hidden rounded-r-2xl border-r border-slate-200 bg-white shadow-2xl transition-transform duration-200 lg:static lg:z-auto lg:w-auto lg:max-w-none lg:translate-x-0 lg:rounded-2xl lg:border lg:shadow-sm ${
            drawer ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center gap-2.5 px-3 py-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-teal-400 via-teal-600 to-indigo-600 text-white shadow-md shadow-teal-900/20">
              <CompassCross className="h-4.5 w-4.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-display text-[13px] font-extrabold leading-tight text-slate-900">Your chats</p>
              <p className="text-[11px] text-slate-500">{chats.data?.length ?? 0} saved · private to you</p>
            </div>
            <button type="button" onClick={() => setDrawer(false)} aria-label="Close chat history"
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-2 px-3 pb-2">
            <button type="button" onClick={newChat}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-600 px-3 py-2.5 text-sm font-bold text-white shadow-sm shadow-teal-900/20 transition hover:-translate-y-0.5 hover:shadow-md">
              <Plus className="h-4 w-4" /> New chat
            </button>
            <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/80 px-2.5 py-1.5 focus-within:border-teal-400 focus-within:bg-white">
              <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search your chats"
                aria-label="Search your chats"
                className="w-full bg-transparent text-[13px] text-slate-700 outline-none placeholder:text-slate-400" />
              {query && (
                <button type="button" onClick={() => setQuery("")} aria-label="Clear search" className="text-slate-400 hover:text-slate-600">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            {chats.loading && <p className="px-3 py-6 text-center text-xs text-slate-400">Loading your chats…</p>}
            {!chats.loading && groups.length === 0 && (
              <div className="mx-1 mt-2 rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center">
                <MessageSquare className="mx-auto h-5 w-5 text-slate-300" />
                <p className="mt-2 text-xs font-medium text-slate-500">
                  {query ? "No chats match that search." : "No chats yet"}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {query ? "Try a different word." : "Ask your first question to start one."}
                </p>
              </div>
            )}

            {groups.map((g) => (
              <div key={g.label} className="mt-3 first:mt-1">
                <p className="px-2 pb-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{g.label}</p>
                <ul className="space-y-0.5">
                  {g.items.map((c) => {
                    const active = c.id === sessionId;
                    return (
                      <li key={c.id} className="relative">
                        <button type="button" onClick={() => openChat(c.id)} aria-current={active ? "true" : undefined}
                          className={`group flex w-full items-start gap-2 rounded-xl px-2.5 py-2 pr-9 text-left transition ${
                            active ? "bg-teal-50 ring-1 ring-teal-200" : "hover:bg-slate-50"
                          }`}>
                          <MessageSquare className={`mt-[3px] h-3.5 w-3.5 shrink-0 ${active ? "text-teal-600" : "text-slate-400"}`} />
                          <span className="min-w-0 flex-1">
                            <span className={`block truncate text-[13px] font-semibold ${active ? "text-teal-900" : "text-slate-700"}`}>
                              {c.title?.trim() || "New chat"}
                            </span>
                            <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-400">
                              <span>{shortDate(c.updated_at)}, {clock(c.updated_at)}</span>
                              <span aria-hidden="true">·</span>
                              <span>{c.message_count} msg</span>
                            </span>
                          </span>
                        </button>

                        {confirmId === c.id ? (
                          <span className="absolute right-1.5 top-2 flex items-center gap-1">
                            <button type="button" onClick={() => removeChat(c.id)}
                              className="rounded-md bg-red-600 px-2 py-1 text-[10px] font-bold text-white hover:bg-red-700">
                              Delete
                            </button>
                            <button type="button" onClick={() => setConfirmId(null)} aria-label="Cancel delete"
                              className="rounded-md bg-white px-1.5 py-1 text-[10px] font-bold text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50">
                              No
                            </button>
                          </span>
                        ) : (
                          <button type="button" onClick={() => setConfirmId(c.id)} aria-label={`Delete chat: ${c.title ?? "New chat"}`}
                            className="absolute right-1.5 top-2 rounded-md p-1.5 text-slate-400 opacity-100 transition hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 lg:opacity-0 lg:group-hover:opacity-100">
                            <Trash className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>

          <div className="border-t border-slate-100 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2.5">
            <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <Check className="h-3 w-3 text-emerald-600" /> Chats are saved to your account
            </p>
          </div>
        </aside>

        {/* ------------------------------------------------ chat panel */}
        <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <header className="flex items-center gap-2 border-b border-slate-100 px-3 py-2.5 sm:px-4">
            <button type="button" onClick={() => setDrawer(true)} aria-label="Open chat history"
              className="-ml-1 rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden">
              <PanelLeft className="h-5 w-5" />
            </button>
            <div className="min-w-0 flex-1">
              <h1 className="truncate font-display text-sm font-extrabold tracking-tight text-slate-900">
                {current?.title?.trim() || "NEET assistant"}
              </h1>
              <p className="truncate text-[11px] text-slate-500">
                {current ? longStamp(current.created_at) : "Cutoffs, counselling, fees and your mock scores"}
              </p>
            </div>
            <span className="hidden items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-100 sm:inline-flex">
              <Sparkle className="h-3 w-3" /> Sources included
            </span>
          </header>

          <div role="log" aria-live="polite" aria-busy={busy} className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6">
            {empty ? (
              <div className="mx-auto flex min-h-full max-w-2xl flex-col items-center justify-center py-2 text-center">
                <Mascot state={mascotState} height={126} className="drop-shadow-xl" />
                <h2 className="mt-2 font-display text-xl font-extrabold tracking-tight text-slate-900 sm:mt-3 sm:text-2xl">
                  How can I help you today?
                </h2>
                <p className="mt-1 max-w-md text-[13px] leading-relaxed text-slate-500">{MASCOT_LINE[mascotState]}</p>
                <div className="mt-4 grid w-full gap-2 sm:mt-5 sm:grid-cols-2">
                  {SUGGESTIONS.map((s, i) => (
                    <button key={s.q} type="button" onClick={() => send(s.q)}
                      className={`group flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left transition hover:-translate-y-0.5 hover:border-teal-300 hover:shadow-sm sm:px-3.5 sm:py-3 ${
                        i >= 3 ? "hidden sm:flex" : ""
                      }`}>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[10px] font-bold uppercase tracking-[0.1em] text-teal-600">{s.tag}</span>
                        <span className="mt-0.5 block text-[13px] font-medium leading-snug text-slate-700">{s.q}</span>
                      </span>
                      <Send className="h-4 w-4 shrink-0 rotate-90 text-slate-300 transition group-hover:text-teal-600" />
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-5">
                {(opening ? [] : msgs).map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex flex-col items-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-teal-700 px-4 py-2.5 text-[14px] leading-relaxed text-white shadow-sm">
                        {m.spoken && <span className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-teal-100"><Mic className="h-3 w-3" /> spoken</span>}
                        <Text s={m.content} />
                      </div>
                      <span className="mt-1 pr-1 text-[10px] text-slate-400">{clock(m.created_at)}</span>
                    </div>
                  ) : (
                    <div key={m.id} className="flex gap-2.5">
                      <MascotAvatar size={28} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[14px] leading-relaxed text-slate-700">
                          <Text s={m.content} />
                        </div>

                        {m.citations.length > 0 && (
                          <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2">
                            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">Sources</p>
                            <ul className="mt-1 space-y-1">
                              {m.citations.map((c, i) => (
                                <li key={i} className="flex flex-wrap items-center gap-1.5 text-[12px] text-slate-600">
                                  <span className="h-1 w-1 rounded-full bg-teal-500" />
                                  {c.url ? (
                                    <a className="font-medium text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-800" href={c.url} target="_blank" rel="noreferrer">{c.source_name}</a>
                                  ) : (
                                    <span className="font-medium">{c.source_name}</span>
                                  )}
                                  {c.year && <span className="text-slate-400">· {c.year}</span>}
                                  {c.page && <span className="text-slate-400">· p.{c.page}</span>}
                                  {c.verification_status && <StatusBadge status={c.verification_status} />}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
                          <span>{clock(m.created_at)}</span>
                          {m.tool_calls.length > 0 && (
                            <span>Looked up: {[...new Set(m.tool_calls)].join(", ").replaceAll("_", " ")}</span>
                          )}
                          {canSpeak && (
                            <button type="button" onClick={() => speech.speak(m.content, lang)}
                              className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:text-teal-800">
                              <Volume className="h-3 w-3" /> Read aloud
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ),
                )}

                {busy && (
                  <div className="flex items-center gap-2.5 text-sm text-slate-500">
                    <MascotAvatar size={28} />
                    <span className="flex items-center gap-1.5 rounded-2xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200/70">
                      <span className="sr-only">Looking that up</span>
                      {[0, 150, 300].map((d) => (
                        <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-teal-500" style={{ animationDelay: `${d}ms` }} />
                      ))}
                    </span>
                  </div>
                )}
                <div ref={end} />
              </div>
            )}
          </div>

          <div className="border-t border-slate-100 px-3 pb-3 pt-2.5 sm:px-5">
            <form className="mx-auto max-w-3xl" onSubmit={(e) => { e.preventDefault(); if (!busy) send(input); }}>
              <div className="flex items-end gap-1.5 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm transition focus-within:border-teal-400 focus-within:ring-4 focus-within:ring-teal-500/10">
                <label htmlFor="q" className="sr-only">Your question</label>
                <textarea
                  id="q"
                  ref={box}
                  rows={1}
                  value={input}
                  maxLength={4000}
                  placeholder="Ask anything about NEET-UG…"
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy) send(input); }
                  }}
                  className="max-h-40 min-h-[38px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[14px] leading-relaxed text-slate-800 outline-none placeholder:text-slate-400"
                />
                {canListen && (
                  <button type="button" onClick={() => (listener.listening ? listener.stop() : listener.start(lang))}
                    disabled={busy} aria-pressed={listener.listening} aria-label={listener.listening ? "Stop listening" : "Ask by voice"}
                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl transition ${
                      listener.listening ? "animate-pulse bg-red-600 text-white" : "text-slate-500 hover:bg-slate-100 hover:text-teal-700"
                    }`}>
                    <Mic className="h-4.5 w-4.5" />
                  </button>
                )}
                <button type="submit" disabled={busy || !input.trim()} aria-label="Send message"
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-teal-700 text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-300">
                  <Send className="h-4 w-4" />
                </button>
              </div>

              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 text-[11px] text-slate-500">
                <span className="hidden items-center gap-1 sm:flex">
                  <kbd className="rounded border border-slate-200 bg-slate-50 px-1 font-sans text-[10px]">Enter</kbd> to send ·
                  <kbd className="rounded border border-slate-200 bg-slate-50 px-1 font-sans text-[10px]">Shift + Enter</kbd> for a new line
                </span>
                <span className="sm:hidden">Answers can be wrong — check official sources.</span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  {canListen && (
                    <label className="flex items-center gap-1.5">
                      <span className="sr-only">Voice language</span>
                      <select className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-600"
                        value={lang} onChange={(e) => setLang(e.target.value)}>
                        {VOICE_LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                      </select>
                    </label>
                  )}
                  {canSpeak && (
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" className="h-3.5 w-3.5 accent-teal-700" checked={readAloud} onChange={(e) => setReadAloud(e.target.checked)} />
                      Read aloud
                    </label>
                  )}
                  {canSpeak && (
                    <label className="flex items-center gap-1.5">
                      <input type="checkbox" className="h-3.5 w-3.5 accent-teal-700" checked={handsFree} onChange={(e) => setHandsFree(e.target.checked)} />
                      Hands-free
                    </label>
                  )}
                  {speech.speaking && (
                    <button type="button" onClick={speech.stop} className="font-semibold text-teal-700 hover:underline">
                      Stop speaking
                    </button>
                  )}
                </span>
              </div>

              {listener.listening && (
                <p className="mt-1 text-[11px] font-medium text-teal-700">
                  {listener.interim || "Listening… speak now"}
                </p>
              )}
              {listener.error && <p role="alert" className="mt-1 text-[11px] text-red-700">{listener.error}</p>}
            </form>
            <p className="mx-auto mt-1 hidden max-w-3xl text-[10px] leading-relaxed text-slate-400 sm:block">
              Answers come from our college database, the predictor and official documents — each with its source. This is
              guidance, not a guarantee; confirm anything important with NTA, MCC or your state authority.
            </p>
          </div>
        </section>
      </div>

      <ErrorBox error={err} />
    </div>
  );
}
