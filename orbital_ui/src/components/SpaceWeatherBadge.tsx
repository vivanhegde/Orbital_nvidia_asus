import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { SpaceWeather } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatSecondsAgo } from "@/lib/time";

export interface SpaceWeatherBadgeProps {
  weather: SpaceWeather | undefined;
  loading: boolean;
  onRefresh: () => void;
  lastDataAt: Date | undefined;
  screeningNote: string | null;
  className?: string;
}

export function SpaceWeatherBadge({
  weather,
  loading,
  onRefresh,
  lastDataAt,
  screeningNote,
  className,
}: SpaceWeatherBadgeProps): React.ReactElement {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-center gap-3 rounded-full border border-cyan-500/25 bg-[rgba(8,15,30,0.72)] px-4 py-2 shadow-lg shadow-black/50 backdrop-blur-md",
        className,
      )}
    >
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="flex items-center gap-3 rounded-md border border-mission-border bg-slate-900/60 px-3 py-2 font-mono text-xs text-slate-200 outline-none transition-[transform,background-color,border-color] duration-200 hover:bg-slate-900 focus-visible:ring-2 focus-visible:ring-cyan-500 active:scale-[0.98]"
            >
              {loading && !weather ? (
                <span className="text-slate-500">Loading SWPC…</span>
              ) : (
                <>
                  <span className="text-cyan-400">Kp {weather?.kp_index?.toFixed(2) ?? "—"}</span>
                  <span className="text-slate-500">|</span>
                  <span>{weather?.geomag_storm_level}</span>
                  <span className="text-slate-500">|</span>
                  <span className="text-amber-300">X-ray {weather?.xray_class}</span>
                </>
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs">
            <p>X-ray flux: {weather?.xray_flux_short?.toExponential(2) ?? "—"} W/m²</p>
            <p className="mt-1 text-slate-400">
              Fetched: {weather?.fetched_at ?? "—"}
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <div className="font-mono text-xs text-slate-500">
        Data age:{" "}
        <span className="text-slate-300">
          {formatSecondsAgo(weather?.fetched_at ?? null)}
        </span>
        {lastDataAt && Number.isFinite(lastDataAt.getTime()) ? (
          <span className="ml-2">
            (poll {lastDataAt.toISOString().slice(11, 19)} UTC)
          </span>
        ) : null}
        {screeningNote ? (
          <span className="ml-2 text-amber-600/80">{screeningNote}</span>
        ) : null}
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0 font-mono text-xs transition-transform duration-200 active:scale-[0.97]"
        onClick={onRefresh}
      >
        Refresh screening
      </Button>
    </div>
  );
}
