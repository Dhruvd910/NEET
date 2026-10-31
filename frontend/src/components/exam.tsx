"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Question text as printed in the NEET booklet: statements on their own lines, and
 * "A. item | I. item" rows from match-the-list questions laid out as a List-I / List-II table.
 */
export function Stem({ text }: { text: string }) {
  const lines = text.split("\n");
  const rows = lines.filter((l) => /^\s*[A-D][.)]\s.+\|\s*[IVX]+[.)]\s/.test(l));
  const blocks: React.ReactNode[] = [];
  let tableDone = false;
  lines.forEach((line, i) => {
    if (rows.includes(line)) {
      if (!tableDone) {
        tableDone = true;
        blocks.push(
          <table key={`t${i}`} className="my-2 w-full border-collapse text-[0.95em]">
            <thead><tr><th className="w-1/2 border border-slate-300 px-2 py-1 text-left">List-I</th>
              <th className="border border-slate-300 px-2 py-1 text-left">List-II</th></tr></thead>
            <tbody>{rows.map((r, j) => {
              const [left, right] = r.split("|").map((x) => x.trim());
              return <tr key={j}><td className="border border-slate-300 px-2 py-1 align-top">{left}</td>
                <td className="border border-slate-300 px-2 py-1 align-top">{right}</td></tr>;
            })}</tbody>
          </table>);
      }
      return;
    }
    if (!line.trim()) return;
    const statement = /^\s*([A-D]|Assertion \(A\)|Reason \(R\))[.:)]/.test(line);
    blocks.push(<p key={i} className={statement ? "pl-4" : ""}>{line}</p>);
  });
  return <div className="space-y-1.5">{blocks}</div>;
}

/** A short exam-hall bell, made with the Web Audio API (no sound file to download). */
export function ringBell(times = 1) {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    for (let i = 0; i < times; i++) {
      const t = ctx.currentTime + i * 0.45;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, t);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.42);
    }
    setTimeout(() => ctx.close(), times * 450 + 200);
  } catch {
    // Sound is a nicety; ignore browsers that block it.
  }
}

/** Rough-work sheet: draw with a finger, stylus or mouse. Like the booklet margins, it is not graded or saved. */
export function RoughPad({ onClose }: { onClose: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [erase, setErase] = useState(false);

  useEffect(() => {
    const c = canvas.current!;
    const ratio = window.devicePixelRatio || 1;
    c.width = c.offsetWidth * ratio;
    c.height = c.offsetHeight * ratio;
    const ctx = c.getContext("2d")!;
    ctx.scale(ratio, ratio);
    ctx.lineCap = ctx.lineJoin = "round";
  }, []);

  const point = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };
  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    drawing.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    const ctx = e.currentTarget.getContext("2d")!;
    ctx.beginPath();
    ctx.moveTo(...point(e));
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const ctx = e.currentTarget.getContext("2d")!;
    ctx.globalCompositeOperation = erase ? "destination-out" : "source-over";
    ctx.lineWidth = erase ? 18 : 2;
    ctx.strokeStyle = "#1e293b";
    ctx.lineTo(...point(e));
    ctx.stroke();
  };
  const clear = () => {
    const c = canvas.current!;
    c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-300 bg-white shadow-2xl" role="dialog" aria-label="Rough work">
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-1.5 text-sm">
        <p className="font-semibold">Rough work</p>
        <p className="hidden text-xs text-slate-500 sm:block">Not graded or saved, like the margins of the booklet.</p>
        <div className="ml-auto flex gap-1.5">
          <button className="btn-ghost !py-1" aria-pressed={erase} onClick={() => setErase(!erase)}>{erase ? "Pen" : "Eraser"}</button>
          <button className="btn-ghost !py-1" onClick={clear}>Clear</button>
          <button className="btn-secondary !py-1" onClick={onClose}>Close</button>
        </div>
      </div>
      <canvas ref={canvas} className="h-[38vh] w-full touch-none bg-[repeating-linear-gradient(#fffef9,#fffef9_27px,#e2e8f0_28px)]"
        onPointerDown={down} onPointerMove={move} onPointerUp={() => { drawing.current = false; }}
        onPointerLeave={() => { drawing.current = false; }} />
    </div>
  );
}
