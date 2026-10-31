"use client";

/* eslint-disable @next/next/no-img-element -- animated WebP; next/image would re-encode and drop the animation */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

export type MascotState = "idle" | "listening" | "thinking" | "talking";

const SRC: Record<MascotState, string> = {
  idle: "/mascot/idle.webp",
  listening: "/mascot/listen.webp",
  thinking: "/mascot/thinking.webp",
  talking: "/mascot/talking.webp",
};
const STILL = "/mascot/idle-still.png";
const LABEL: Record<MascotState, string> = {
  idle: "Assistant mascot, waiting for your question",
  listening: "Assistant mascot, listening",
  thinking: "Assistant mascot, thinking",
  talking: "Assistant mascot, talking",
};
const loaded = new Set<string>();

function subscribeMotion(cb: () => void) {
  const m = window.matchMedia("(prefers-reduced-motion: reduce)");
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
}

/** Still image for users who prefer reduced motion or have turned on data saver. */
function useStill() {
  return useSyncExternalStore(subscribeMotion, () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData), () => false);
}

/**
 * The assistant's animated mascot. Only the idle animation loads up front; each other animation is
 * fetched the first time it is needed, and the current one stays on screen until the next has loaded,
 * so there is never a blank frame.
 */
export default function Mascot({ state, height = 200, className = "" }: { state: MascotState; height?: number; className?: string }) {
  const still = useStill();
  const target = still ? STILL : SRC[state];
  const [shown, setShown] = useState(target);

  useEffect(() => {
    if (loaded.has(target)) { setShown(target); return; }
    let cancelled = false;
    const img = new Image();
    img.onload = () => { loaded.add(target); if (!cancelled) setShown(target); };
    img.src = target;
    return () => { cancelled = true; };
  }, [target]);

  return (
    <img src={shown} alt={LABEL[state]} onLoad={() => loaded.add(shown)}
      style={{ height, width: "auto" }} className={`select-none ${className}`} draggable={false} />
  );
}

/** Small round avatar used next to assistant messages. */
export function MascotAvatar({ size = 32 }: { size?: number }) {
  return <img src="/mascot/avatar-circle.png" alt="" aria-hidden="true" width={size} height={size}
    className="shrink-0 rounded-full bg-sky-50 object-cover ring-1 ring-sky-200" style={{ width: size, height: size }} />;
}

/** Floating "ask me" button on every page except the assistant itself and the exam room (no distractions). */
export function MascotLauncher() {
  const path = usePathname();
  if (path.startsWith("/assistant") || /^\/practice\/\d+/.test(path) || path.startsWith("/guardian-consent")) return null;
  return (
    <Link href="/assistant" aria-label="Ask the NEET assistant"
      className="group fixed right-4 bottom-4 z-30 flex items-end gap-2 print:hidden">
      <span className="mb-3 hidden rounded-full bg-white px-3 py-1.5 text-sm text-slate-800 shadow-md ring-1 ring-slate-200 group-hover:block sm:block">
        Ask me anything
      </span>
      <span className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-full bg-sky-50 shadow-lg ring-2 ring-sky-300 transition group-hover:scale-105">
        <img src="/mascot/avatar-circle.png" alt="" aria-hidden="true" className="h-full w-full rounded-full object-cover" />
      </span>
    </Link>
  );
}
