// Exam room helpers. The server renders and saves everything; this script only does what needs the browser:
// the ticking clock and bells, full screen, the rough-work pad, noticing when the student leaves the window,
// and adding the seconds spent on the current question to each click.
(function () {
  const room = () => document.getElementById("exam-room");
  const csrf = () => { try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || ""; } catch { return ""; } };

  function ringBell(times) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      for (let i = 0; i < times; i++) {
        const t = ctx.currentTime + i * 0.45, osc = ctx.createOscillator(), gain = ctx.createGain();
        osc.frequency.setValueAtTime(880, t);
        gain.gain.setValueAtTime(0.0001, t);
        gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
        osc.connect(gain).connect(ctx.destination);
        osc.start(t);
        osc.stop(t + 0.42);
      }
      setTimeout(() => ctx.close(), times * 450 + 200);
    } catch { /* sound is a nicety */ }
  }

  function announce(text) {
    const el = document.getElementById("announcement");
    if (!el) return;
    el.textContent = "🔔 " + text;
    el.classList.replace("hidden", "flex");
    clearTimeout(announce.t);
    announce.t = setTimeout(() => el.classList.replace("flex", "hidden"), 8000);
  }

  // ---------------------------------------------------------------- clock (the server is the real clock)
  let remaining = null, submitting = false, leaving = false;
  const fmt = (s) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };

  function submit(auto) {
    if (submitting || !room()) return;
    submitting = leaving = true;
    if (auto) { announce("Time is up. Pens down — your answer sheet is being collected."); ringBell(3); }
    htmx.ajax("POST", `/practice/${room().dataset.attempt}/submit`, { values: { auto: auto ? "1" : "" }, swap: "none" });
  }

  setInterval(() => {
    if (remaining === null || !room()) return;
    remaining = Math.max(0, remaining - 1);
    const clock = room().querySelector("[data-clock]");
    if (clock) clock.textContent = fmt(remaining);
    if (remaining <= 300) room().querySelector("#exam-clock")?.classList.add("animate-pulse", "bg-red-100", "text-red-800");
    const notes = JSON.parse(room().dataset.announcements || "{}");
    if (notes[remaining] && remaining < Number(room().dataset.duration)) { announce(notes[remaining]); ringBell(1); }
    if (remaining === 0) submit(true);
  }, 1000);

  // ---------------------------------------------------------------- seconds spent on the current question
  let enteredAt = Date.now(), currentQ = null;
  function sync() {
    const state = room()?.querySelector("[data-remaining]");
    if (!state) return;
    remaining = Number(state.dataset.remaining);
    if (state.dataset.cur !== currentQ) { currentQ = state.dataset.cur; enteredAt = Date.now(); }
  }
  document.addEventListener("htmx:configRequest", (e) => {
    if (!e.detail.path.endsWith("/act")) return;
    e.detail.parameters.elapsed = Math.min(3600, Math.round((Date.now() - enteredAt) / 1000));
    enteredAt = Date.now();
  });
  document.addEventListener("htmx:beforeRequest", (e) => { if (e.detail.pathInfo?.requestPath?.endsWith("/submit")) leaving = true; });
  document.addEventListener("htmx:afterSettle", sync);
  window.addEventListener("load", sync);

  // ---------------------------------------------------------------- starting: full screen and the opening bell
  document.addEventListener("submit", (e) => {
    const form = e.target.closest("[data-exam-start]");
    if (form && form.querySelector("[name=fullscreen]")?.checked) {
      document.documentElement.requestFullscreen?.()?.catch(() => undefined);  // not awaited: some browsers never settle it
    }
  });
  // Fires before the room is swapped in, so wait for it to be on the page.
  document.body.addEventListener("exam-started", () => {
    ringBell(2);
    setTimeout(() => announce("The exam has begun. All the best, future doctor!"), 400);
  });

  // ---------------------------------------------------------------- leaving the window / the page
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "hidden" || !room() || submitting) return;
    fetch(`/api/exams/attempts/${room().dataset.attempt}/focus-lost`, { method: "POST", headers: { "X-CSRF-Token": csrf() } }).catch(() => undefined);
    announce("You left the exam window. This is noted in your result.");
  });
  window.addEventListener("beforeunload", (e) => { if (room() && !leaving) e.preventDefault(); });

  // ---------------------------------------------------------------- buttons: full screen and rough work
  let drawing = false, erase = false;
  function setupPad(canvas) {
    if (canvas.dataset.ready) return;
    canvas.dataset.ready = "1";
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.lineCap = ctx.lineJoin = "round";
    const pt = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    canvas.addEventListener("pointerdown", (e) => { drawing = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pt(e)); });
    canvas.addEventListener("pointermove", (e) => {
      if (!drawing) return;
      ctx.globalCompositeOperation = erase ? "destination-out" : "source-over";
      ctx.lineWidth = erase ? 18 : 2;
      ctx.strokeStyle = "#1e293b";
      ctx.lineTo(...pt(e));
      ctx.stroke();
    });
    ["pointerup", "pointerleave"].forEach((t) => canvas.addEventListener(t, () => { drawing = false; }));
  }

  document.addEventListener("click", (e) => {
    const pad = document.getElementById("rough-pad");
    if (e.target.closest("[data-fullscreen]")) {
      (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.())?.catch?.(() => undefined);
    } else if (e.target.closest("[data-toggle-rough]") && pad) {
      pad.classList.toggle("hidden");
      room().classList.toggle("pb-[42vh]", !pad.classList.contains("hidden"));
      setupPad(pad.querySelector("canvas"));
    } else if (e.target.closest("[data-rough]") && pad) {
      const action = e.target.closest("[data-rough]").dataset.rough, canvas = pad.querySelector("canvas");
      if (action === "close") { pad.classList.add("hidden"); room().classList.remove("pb-[42vh]"); }
      if (action === "clear") canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      if (action === "erase") { erase = !erase; e.target.textContent = erase ? "Pen" : "Eraser"; e.target.setAttribute("aria-pressed", erase); }
    }
  });
})();
