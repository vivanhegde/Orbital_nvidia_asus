import * as React from "react";

import type { SatellitePosition } from "@/lib/types";
import { Button } from "@/components/ui/button";

export interface SatelliteInfoCardProps {
  satellite: SatellitePosition | null;
  onClose: () => void;
}

function fmtDeg(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(2)}°`;
}

function fmtAltKm(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(1)} km`;
}

export function SatelliteInfoCard({
  satellite,
  onClose,
}: SatelliteInfoCardProps): React.ReactElement | null {
  if (!satellite) return null;
  return (
    <div className="pointer-events-auto w-[300px] animate-missions-sat-card rounded-lg border border-cyan-500/20 bg-[rgba(8,15,30,0.72)] p-3 shadow-lg shadow-black/50 backdrop-blur-md">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-sm font-medium text-slate-100">
            {satellite.name ?? "—"}
          </p>
          <p className="mt-1 font-mono text-xs text-slate-400">
            NORAD {satellite.norad_id ?? "—"} · {satellite.type ?? "—"} ·{" "}
            {satellite.source_group ?? "—"}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 px-2 font-mono text-xs text-slate-400"
          onClick={onClose}
        >
          ✕
        </Button>
      </div>
      <dl className="mt-2 space-y-1 font-mono text-xs text-slate-300">
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Lat</dt>
          <dd>{fmtDeg(satellite.lat)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Lon</dt>
          <dd>{fmtDeg(satellite.lon)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Altitude</dt>
          <dd>{fmtAltKm(satellite.alt_km)}</dd>
        </div>
      </dl>
    </div>
  );
}
