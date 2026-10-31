// Compare tray: remembers up to 5 college ids in this browser (convenience only, never sent anywhere)
// and links to /compare?ids=… . Buttons opt in with data-compare="<id>".
(function () {
  const KEY = "neet-compare";
  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } };
  const write = (ids) => { try { localStorage.setItem(KEY, JSON.stringify(ids)); } catch { /* storage blocked */ } };

  function refresh() {
    const ids = read();
    document.querySelectorAll("[data-compare]").forEach((b) => {
      const on = ids.includes(Number(b.dataset.compare));
      b.textContent = on ? "✓ In compare" : "+ Compare";
      b.setAttribute("aria-pressed", String(on));
    });
    document.querySelectorAll("[data-compare-count]").forEach((el) => { el.textContent = ids.length; });
    document.querySelectorAll("[data-compare-link]").forEach((a) => {
      a.href = "/compare?ids=" + ids.join(",");
      a.classList.toggle("hidden", ids.length === 0);
    });
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-compare]");
    if (!b) return;
    const id = Number(b.dataset.compare);
    let ids = read();
    ids = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id].slice(-5);
    write(ids);
    refresh();
  });
  // On the compare page the URL is the source of truth; opening /compare without ids uses the remembered ones.
  function syncComparePage() {
    const page = document.querySelector("[data-compare-ids]");
    if (!page) return;
    const urlIds = page.dataset.compareIds.split(",").filter(Boolean).map(Number);
    const stored = read();
    if (!urlIds.length && stored.length && !new URLSearchParams(location.search).has("ids")) {
      location.replace("/compare?ids=" + stored.join(","));
      return;
    }
    write(urlIds);
  }

  document.addEventListener("DOMContentLoaded", () => { syncComparePage(); refresh(); });
  document.addEventListener("htmx:afterSettle", () => { syncComparePage(); refresh(); });
  refresh();
})();
