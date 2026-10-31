"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { Notice, StatusBadge } from "@/components/ui";
import { fmtDate } from "@/lib/api";

export type Place = { kind: string; category: string; name: string; distance_km: number | null; walk_minutes: number | null;
  route_url: string | null; latitude: number | null; longitude: number | null; price_range: string | null; provider: string;
  attribution: string | null; is_demo: boolean; last_checked_at: string | null };

const KIND_LABEL: Record<string, string> = {
  bus_stop: "Bus stop", railway: "Railway station", metro: "Metro station", airport: "Airport",
  hospital: "Hospital", clinic: "Clinic / doctor", pharmacy: "Pharmacy", police: "Police station",
  restaurant: "Restaurant / mess", cafe: "Café", stay: "Hostel / guest house", pg: "PG / private hostel",
  grocery: "Grocery / market", bank_atm: "Bank / ATM", atm: "Bank / ATM", laundry: "Laundry", stationery: "Stationery / books / xerox",
  library: "Library", gym: "Gym", park: "Park", mall: "Mall / cinema",
};
const CATEGORY_ORDER = ["Getting around", "Health & safety", "Food", "Stay (outside campus)", "Daily needs", "Study & leisure", "Other"];
const CATEGORY_HINT: Record<string, string> = {
  "Stay (outside campus)": "Listings come from map data, not inspections. Visit before paying, check safety, and ask current students.",
  "Health & safety": "In an emergency call 112.",
};
// OpenStreetMap's own tiles are for light use only. Production sites should set a tile provider they have a plan with.
const TILE_URL = process.env.NEXT_PUBLIC_MAP_TILE_URL ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION = process.env.NEXT_PUBLIC_MAP_ATTRIBUTION ?? "© OpenStreetMap contributors";

function NearbyMap({ lat, lon, places, name }: { lat: number; lon: number; places: Place[]; name: string }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let map: import("leaflet").Map | undefined;
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !el.current) return;
      map = L.map(el.current, { scrollWheelZoom: false }).setView([lat, lon], 14);
      L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(map);
      L.circleMarker([lat, lon], { radius: 9, color: "#0f766e", fillOpacity: 0.9 }).addTo(map).bindPopup(`<strong>${name}</strong>`);
      for (const p of places) {
        if (p.latitude == null || p.longitude == null) continue;
        L.circleMarker([p.latitude, p.longitude], { radius: 5, color: "#475569", fillOpacity: 0.7 })
          .addTo(map).bindPopup(`${p.name}<br/>${KIND_LABEL[p.kind] ?? p.kind} · ${p.distance_km ?? "?"} km`);
      }
    })();
    return () => { cancelled = true; map?.remove(); };
  }, [lat, lon, places, name]);
  return <div ref={el} className="h-72 w-full rounded-lg border border-slate-200" role="region" aria-label="Map of places around the college" />;
}

export default function NearbyPanel({ places, lat, lon, collegeName, isDemo }: { places: Place[]; lat: number | null; lon: number | null;
  collegeName: string; isDemo: boolean }) {
  const [category, setCategory] = useState<string>("All");
  const groups = CATEGORY_ORDER.map((c) => [c, places.filter((p) => p.category === c)
    .sort((a, b) => (a.distance_km ?? 999) - (b.distance_km ?? 999))] as const).filter(([, ps]) => ps.length > 0);
  const shown = category === "All" ? groups : groups.filter(([c]) => c === category);
  const attribution = places.find((p) => p.attribution)?.attribution;

  return (
    <section className="space-y-4 text-sm">
      <Notice>
        Distances are straight-line and walking times are rough estimates. We never claim a place is open, safe or has
        rooms available right now. Check with the place and with current students.
      </Notice>
      {lat != null && lon != null ? (
        <NearbyMap lat={lat} lon={lon} places={places} name={collegeName} />
      ) : (
        <p className="text-xs text-slate-500">
          {isDemo ? "Map hidden: demo colleges have fictional locations." : "Map shown once the college's verified location is added."}
        </p>
      )}
      {places.length === 0 ? <p className="muted">No nearby places recorded for this college yet.</p> : (
        <>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
            {["All", ...groups.map(([c]) => c)].map((c) => (
              <button key={c} onClick={() => setCategory(c)} aria-pressed={category === c}
                className={`rounded-full px-3 py-1 text-xs ring-1 ${category === c ? "bg-teal-700 text-white ring-teal-700" : "bg-white text-slate-700 ring-slate-300"}`}>{c}</button>))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {shown.map(([cat, ps]) => (
              <div key={cat} className="card">
                <h3 className="font-semibold">{cat}</h3>
                {CATEGORY_HINT[cat] && <p className="mt-0.5 text-xs text-amber-800">{CATEGORY_HINT[cat]}</p>}
                <ul className="mt-2 divide-y divide-slate-100">
                  {ps.map((p, i) => (
                    <li key={i} className="flex items-start justify-between gap-3 py-1.5">
                      <div className="min-w-0">
                        <p className="truncate">
                          {p.route_url ? <a className="underline" href={p.route_url} target="_blank" rel="noreferrer">{p.name}</a> : p.name}
                          {p.is_demo && <> <StatusBadge status="demo" /></>}
                        </p>
                        <p className="text-xs text-slate-500">{KIND_LABEL[p.kind] ?? p.kind}{p.price_range && ` · ${p.price_range}`}</p>
                      </div>
                      <div className="shrink-0 text-right text-xs text-slate-600">
                        <p>{p.distance_km != null ? `${p.distance_km} km` : "—"}</p>
                        {p.walk_minutes != null && <p>~{p.walk_minutes} min walk</p>}
                      </div>
                    </li>))}
                </ul>
              </div>))}
          </div>
          <p className="text-xs text-slate-500">
            Source: {places[0].provider}{attribution && ` · Map data ${attribution}`} · Last checked {fmtDate(places[0].last_checked_at)}
          </p>
        </>
      )}
    </section>
  );
}
