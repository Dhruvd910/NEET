// Draws the college and its nearby places on an OpenStreetMap map (Leaflet). Data comes from the page.
(function () {
  function draw() {
    const el = document.getElementById("nearby-map");
    if (!el || !window.L || el.dataset.drawn) return;
    el.dataset.drawn = "1";
    const lat = Number(el.dataset.lat), lon = Number(el.dataset.lon);
    const map = L.map(el, { scrollWheelZoom: false }).setView([lat, lon], 14);
    L.tileLayer(el.dataset.tiles || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { attribution: el.dataset.attribution || "© OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
    const label = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    L.circleMarker([lat, lon], { radius: 9, color: "#0f766e", fillOpacity: 0.9 }).addTo(map).bindPopup("<strong>" + label(el.dataset.name) + "</strong>");
    for (const p of JSON.parse(el.dataset.places || "[]")) {
      L.circleMarker([p.lat, p.lon], { radius: 5, color: "#475569", fillOpacity: 0.7 })
        .addTo(map).bindPopup(label(p.name) + "<br>" + label(p.kind) + " · " + (p.km ?? "?") + " km");
    }
  }
  window.addEventListener("load", draw);
  document.addEventListener("htmx:afterSettle", draw);
})();
