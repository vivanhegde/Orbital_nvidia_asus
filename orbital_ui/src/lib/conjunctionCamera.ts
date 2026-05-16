import type { FlaggedConjunction, SatellitePosition } from "@/lib/types";

/**
 * Unit ECEF direction from geodetic (WGS84-style lat/lon) on a sphere.
 * Using surface normals gives a stable geographic aim for close LEO pairs;
 * full spherical r = R+alt was skewing the aim vs API geodetic output.
 */
function unitFromLatLon(
  latDeg: number,
  lonDeg: number,
): [number, number, number] {
  const φ = (latDeg * Math.PI) / 180;
  const λ = (lonDeg * Math.PI) / 180;
  const cφ = Math.cos(φ);
  return [cφ * Math.cos(λ), cφ * Math.sin(λ), Math.sin(φ)];
}

function geodeticFromDirection(
  x: number,
  y: number,
  z: number,
): { lat: number; lon: number } {
  const len = Math.hypot(x, y, z);
  if (len < 1e-9) return { lat: 0, lon: 0 };
  const ux = x / len;
  const uy = y / len;
  const uz = z / len;
  const lat = (Math.asin(Math.min(1, Math.max(-1, uz))) * 180) / Math.PI;
  const lon = (Math.atan2(uy, ux) * 180) / Math.PI;
  return { lat, lon };
}

/**
 * Great-circle midpoint between subsatellite points (good for close approaches).
 */
export function conjunctionNadirFromPositions(
  rows: SatellitePosition[],
  c: FlaggedConjunction,
): { lat: number; lon: number } | null {
  const a = rows.find((r) => r.norad_id === c.obj1.norad_id);
  const b = rows.find((r) => r.norad_id === c.obj2.norad_id);
  if (a && b) {
    const [x1, y1, z1] = unitFromLatLon(a.lat, a.lon);
    const [x2, y2, z2] = unitFromLatLon(b.lat, b.lon);
    return geodeticFromDirection(x1 + x2, y1 + y2, z1 + z2);
  }
  const one = a ?? b ?? rows[0];
  return one ? { lat: one.lat, lon: one.lon } : null;
}

/**
 * Camera altitude for react-globe.gl `pointOfView` (in globe-radii above surface).
 * Lower = more zoomed in. Default overview is ~2.5; we zoom much closer for conjunctions.
 */
export function globeAltitudeForMissKm(missKm: number): number {
  const d = Math.max(0, missKm);
  if (d < 2) return 0.45;
  if (d < 30) return 0.7;
  if (d < 200) return 1.0;
  if (d < 2_000) return 1.4;
  return 1.8;
}
