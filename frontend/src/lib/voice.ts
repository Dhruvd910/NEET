"use client";

/**
 * Voice input and output using the browser's built-in speech services (free; no audio reaches our servers).
 * - Speech-to-text: Web Speech API (Chrome, Edge, Safari). In Chrome the browser sends audio to Google's
 *   speech service; we only receive the recognised text.
 * - Text-to-speech: speechSynthesis with an Indian-English or Hindi voice when the device has one.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean; maxAlternatives: number;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
};
type RecognitionCtor = new () => Recognition;

export const VOICE_LANGS = [
  { code: "en-IN", label: "English (India)" },
  { code: "hi-IN", label: "हिन्दी (Hindi)" },
] as const;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const noop = () => () => {};
export function useVoiceSupport() {
  const canListen = useSyncExternalStore(noop, () => recognitionCtor() !== null, () => false);
  const canSpeak = useSyncExternalStore(noop, () => typeof window !== "undefined" && "speechSynthesis" in window, () => false);
  return { canListen, canSpeak };
}

/** Turns an on-screen answer into something pleasant to hear. */
export function toSpeech(text: string): string {
  return text
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\*\*|__|`|#+\s/g, "")
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/₹\s?/g, "rupees ")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\.\s*\./g, ".")
    .trim();
}

export function useSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const stop = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text: string, lang: string, onDone?: () => void) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return onDone?.();
    const synth = window.speechSynthesis;
    synth.cancel();
    const voices = synth.getVoices();
    const voice = voices.find((v) => v.lang === lang) ?? voices.find((v) => v.lang.startsWith(lang.slice(0, 2)));
    // Some browsers stop long utterances part-way, so speak sentence by sentence.
    const parts = toSpeech(text).match(/[^.!?।]+[.!?।]?/g)?.map((p) => p.trim()).filter(Boolean) ?? [];
    if (!parts.length) return onDone?.();
    setSpeaking(true);
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = lang;
      if (voice) u.voice = voice;
      u.rate = 1;
      if (i === parts.length - 1) {
        u.onend = () => { setSpeaking(false); onDone?.(); };
        u.onerror = () => { setSpeaking(false); };
      }
      synth.speak(u);
    });
  }, []);

  useEffect(() => stop, [stop]);
  return { speak, stop, speaking };
}

export function useListener(onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<Recognition | null>(null);
  const finalText = useRef("");
  const onFinalRef = useRef(onFinal);
  useEffect(() => { onFinalRef.current = onFinal; }, [onFinal]);

  const start = useCallback((lang: string) => {
    const Ctor = recognitionCtor();
    if (!Ctor) return setError("Voice input isn't supported in this browser. Try Chrome or Edge.");
    rec.current?.abort();
    const r = new Ctor();
    r.lang = lang;
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;
    finalText.current = "";
    r.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText.current += res[0].transcript;
        else live += res[0].transcript;
      }
      setInterim((finalText.current + " " + live).trim());
    };
    r.onerror = (e) => {
      setError(e.error === "not-allowed" || e.error === "service-not-allowed"
        ? "Microphone permission was blocked. Allow the microphone for this site and try again."
        : e.error === "no-speech" ? "I didn't hear anything. Tap the mic and try again." : `Voice input stopped (${e.error}).`);
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
      const text = finalText.current.trim();
      if (text) onFinalRef.current(text);
    };
    rec.current = r;
    setError(null);
    setListening(true);
    r.start();
  }, []);

  const stop = useCallback(() => rec.current?.stop(), []);
  useEffect(() => () => rec.current?.abort(), []);
  return { start, stop, listening, interim, error };
}
