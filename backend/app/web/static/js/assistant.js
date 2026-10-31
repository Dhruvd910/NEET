// Assistant page helpers. The server sends and stores every message; this script only does browser-only work:
// voice input and read-aloud (the browser's own speech services, so no audio reaches our server), the mascot's
// animation, showing the question straight away while the answer loads, and Enter-to-send.
(function () {
  const $ = (s) => document.querySelector(s);
  const MASCOT = { idle: "idle.webp", listening: "listen.webp", thinking: "thinking.webp", talking: "talking.webp" };
  const LINE = { idle: "Ask me anything about NEET-UG — cutoffs, colleges, counselling or your own mock scores.",
    listening: "I'm listening…", thinking: "Let me look that up…", talking: "Here's what I found." };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || navigator.connection?.saveData;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canSpeak = "speechSynthesis" in window;
  let listening = false, speaking = false, recognizer = null;

  function mascot(state) {
    const img = $("#mascot");
    if (img) {
      const src = "/static/mascot/" + (still ? "idle-still.png" : MASCOT[state]);
      const pre = new Image();  // keep the current frame until the next animation has loaded
      pre.onload = () => { img.src = src; };
      pre.src = src;
      img.alt = "Assistant mascot, " + (state === "idle" ? "waiting for your question" : state);
    }
    const line = $("#mascot-line");
    if (line) line.textContent = LINE[state];
  }
  const stateNow = () => (listening ? "listening" : speaking ? "talking" : "idle");

  // ---------------------------------------------------------------- read aloud
  const toSpeech = (t) => t.replace(/https?:\/\/\S+/g, "").replace(/^\s*[-*•]\s+/gm, "").replace(/₹\s?/g, "rupees ")
    .replace(/\s*\n+\s*/g, ". ").replace(/\.\s*\./g, ".").trim();
  const lang = () => $("[data-voice-lang]")?.value || "en-IN";

  function speak(text, onDone) {
    if (!canSpeak) return onDone?.();
    const synth = speechSynthesis;
    synth.cancel();
    const voices = synth.getVoices(), l = lang();
    const voice = voices.find((v) => v.lang === l) || voices.find((v) => v.lang.startsWith(l.slice(0, 2)));
    const parts = (toSpeech(text).match(/[^.!?।]+[.!?।]?/g) || []).map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return onDone?.();  // some browsers stop long utterances, so speak sentence by sentence
    speaking = true;
    $("[data-stop-speaking]")?.classList.remove("hidden");
    mascot("talking");
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = l;
      if (voice) u.voice = voice;
      if (i === parts.length - 1) {
        u.onend = () => { stopSpeaking(); onDone?.(); };
        u.onerror = stopSpeaking;
      }
      synth.speak(u);
    });
  }
  function stopSpeaking() {
    if (canSpeak) speechSynthesis.cancel();
    speaking = false;
    $("[data-stop-speaking]")?.classList.add("hidden");
    mascot(stateNow());
  }

  // ---------------------------------------------------------------- voice input
  function status(text, error) {
    const el = $("[data-voice-status]");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
    el.classList.toggle("text-red-700", !!error);
    el.classList.toggle("text-teal-700", !error);
  }
  function listen() {
    if (!Recognition) return status("Voice input isn't supported in this browser. Try Chrome or Edge.", true);
    stopSpeaking();
    recognizer?.abort();
    const r = new Recognition();
    let finalText = "";
    Object.assign(r, { lang: lang(), interimResults: true, continuous: false, maxAlternatives: 1 });
    r.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else live += e.results[i][0].transcript;
      }
      status((finalText + " " + live).trim() || "Listening… speak now");
    };
    r.onerror = (e) => status(e.error === "not-allowed" || e.error === "service-not-allowed"
      ? "Microphone permission was blocked. Allow the microphone for this site and try again."
      : e.error === "no-speech" ? "I didn't hear anything. Tap the mic and try again." : `Voice input stopped (${e.error}).`, true);
    r.onend = () => {
      listening = false;
      setMic();
      if (!$("[data-voice-status]")?.classList.contains("text-red-700")) status("");
      if (finalText.trim()) send(finalText.trim(), true);
    };
    recognizer = r;
    listening = true;
    setMic();
    status("Listening… speak now");
    r.start();
  }
  function setMic() {
    const b = $("[data-mic]");
    if (!b) return;
    b.setAttribute("aria-pressed", String(listening));
    b.setAttribute("aria-label", listening ? "Stop listening" : "Ask by voice");
    b.classList.toggle("animate-pulse", listening);
    b.classList.toggle("bg-red-600", listening);
    b.classList.toggle("text-white", listening);
    mascot(stateNow());
  }

  // ---------------------------------------------------------------- sending
  function send(text, voice) {
    const form = $("#composer");
    if (!form || !text.trim()) return;
    form.content.value = text;
    form.voice.value = voice ? "1" : "";
    htmx.trigger(form, "submit");
  }
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  document.addEventListener("htmx:beforeRequest", (e) => {
    if (e.detail.elt.id !== "composer") return;
    stopSpeaking();
    // Show the question straight away; the server's page replaces it when the answer arrives.
    const text = e.detail.elt.content.value.trim();
    $("#welcome")?.classList.add("hidden");
    $("#typing")?.insertAdjacentHTML("beforebegin",
      `<div class="flex flex-col items-end"><div class="max-w-[85%] whitespace-pre-line rounded-2xl rounded-br-md bg-teal-700 px-4 py-2.5 text-[14px] leading-relaxed text-white shadow-sm">${esc(text)}</div></div>`);
    $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  });

  function setup() {
    const log = $("#chat-log");
    if (log) log.scrollTop = log.scrollHeight;
    if (Recognition) $("[data-mic]")?.classList.replace("hidden", "grid");
    if (Recognition || canSpeak) $("[data-voice-controls]")?.removeAttribute("hidden");
    if (canSpeak) document.querySelectorAll("[data-read-aloud]").forEach((b) => b.classList.replace("hidden", "inline-flex"));
    // Answer to a spoken question: read it out, then listen again in hands-free mode.
    const fresh = $("[data-speak] [data-answer]");
    if (fresh && $("[data-read-toggle]")?.checked !== false) {
      speak(fresh.innerText, () => { if ($("[data-hands-free]")?.checked) listen(); });
    }
    setMic();
  }
  // Keep the voice settings across page swaps.
  let saved = {};
  document.addEventListener("htmx:beforeSwap", () => {
    saved = { lang: lang(), read: $("[data-read-toggle]")?.checked, hands: $("[data-hands-free]")?.checked };
  });
  document.addEventListener("htmx:afterSettle", () => {
    if (saved.lang && $("[data-voice-lang]")) $("[data-voice-lang]").value = saved.lang;
    if (saved.read !== undefined && $("[data-read-toggle]")) $("[data-read-toggle]").checked = saved.read;
    if (saved.hands !== undefined && $("[data-hands-free]")) $("[data-hands-free]").checked = saved.hands;
    setup();
  });
  window.addEventListener("load", setup);

  document.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("[data-mic]")) return listening ? recognizer?.stop() : listen();
    if (t.closest("[data-stop-speaking]")) return stopSpeaking();
    if (t.closest("[data-suggest]")) return send(t.closest("[data-suggest]").dataset.suggest, false);
    const read = t.closest("[data-read-aloud]");
    if (read) speak(read.closest("[data-msg]").querySelector("[data-answer]").innerText);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.id === "q" && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.target.value.trim() && !e.target.form.querySelector("[type=submit]").disabled) send(e.target.value, false);
    }
  });
  document.addEventListener("input", (e) => {  // grow the box with its text
    if (e.target.id !== "q") return;
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  });
})();
