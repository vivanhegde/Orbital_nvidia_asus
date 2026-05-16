import type { SatellitePosition } from "@/lib/types";

/** Operational live-dot styling (rendered via Globe ``pointsData`` in GlobeView). */

export const LIVE_POINT_BASE_RADIUS = 0.3;
export const LIVE_POINT_HIGHLIGHT_RADIUS_LOW = 0.3;
export const LIVE_POINT_HIGHLIGHT_RADIUS_HIGH = 0.45;
export const LIVE_POINT_INTENSE_RADIUS = 0.5;
export const LIVE_POINT_RESOLUTION = 8;
export const POINTS_TRANSITION_MS = 5000;

export function liveTypeColor(t: SatellitePosition["type"]): string {
  if (t === "payload") return "#38bdf8";
  if (t === "rocket_body") return "#a78bfa";
  return "#f97316";
}

export function livePointColor(
  p: SatellitePosition,
  conjunctionStatusMap: ReadonlyMap<number, string>,
): string {
  const status = conjunctionStatusMap.get(p.norad_id);
  if (status === "action") return "#ef4444"; // red
  if (status === "watch") return "#facc15"; // yellow
  if (status === "noise") return "#22c55e"; // green
  return "#38bdf8"; // light blue
}

export function livePointRadius(
  p: SatellitePosition,
  conjunctionStatusMap: ReadonlyMap<number, string>,
  intenseNorads: ReadonlySet<number>,
  hiPulse: boolean,
): number {
  if (intenseNorads.has(p.norad_id)) return LIVE_POINT_INTENSE_RADIUS;
  if (conjunctionStatusMap.has(p.norad_id)) {
    return hiPulse
      ? LIVE_POINT_HIGHLIGHT_RADIUS_HIGH
      : LIVE_POINT_HIGHLIGHT_RADIUS_LOW;
  }
  return LIVE_POINT_BASE_RADIUS;
}

export function livePointLabelHtml(p: SatellitePosition): string {
  return `<div style="font-family:ui-monospace,monospace;font-size:11px;padding:4px 6px;background:rgba(8,15,30,0.92);border:1px solid rgba(56,189,248,0.35);border-radius:4px;color:#e2e8f0"><b>${p.name}</b><br/><span style="color:#94a3b8">${p.type} · ${p.alt_km.toFixed(0)} km · click for details</span></div>`;
}
