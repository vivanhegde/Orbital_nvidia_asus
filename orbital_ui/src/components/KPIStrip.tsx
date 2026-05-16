import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { CatalogSummary, FlaggedConjunction, SpaceWeather } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatSecondsAgo } from "@/lib/time";

function stormTone(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("quiet") || l.includes("unsettled")) return "text-emerald-400";
  if (l === "active" || l.startsWith("g1")) return "text-amber-400";
  return "text-red-400";
}

export interface KPIStripProps {
  summary: CatalogSummary | undefined;
  summaryLoading: boolean;
  flagged: FlaggedConjunction[] | undefined;
  flaggedLoading: boolean;
  spaceWeather: SpaceWeather | undefined;
  spaceLoading: boolean;
  className?: string;
}

export function KPIStrip({
  summary,
  summaryLoading,
  flagged,
  flaggedLoading,
  spaceWeather,
  spaceLoading,
  className,
}: KPIStripProps): React.ReactElement {
  const critical =
    flagged?.filter((c) => c.pc_band === "action").length ?? null;
  const watch =
    flagged?.filter((c) => c.pc_band === "watch").length ?? null;

  return (
    <div
      className={cn(
        "grid h-20 grid-cols-2 gap-2 md:h-[4.75rem] md:grid-cols-5",
        className,
      )}
    >
      <Card className="border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md">
        <CardContent className="p-3 pt-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            Total tracked
          </p>
          {summaryLoading && !summary ? (
            <Skeleton className="mt-1 h-6 w-16" />
          ) : (
            <p className="mt-1 font-mono text-xl font-medium text-cyan-300">
              {summary?.total_objects ?? "—"}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md">
        <CardContent className="p-3 pt-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            Critical (Pc ≥ 1e-4)
          </p>
          {flaggedLoading && !flagged ? (
            <Skeleton className="mt-1 h-6 w-10" />
          ) : (
            <p className="mt-1 font-mono text-xl font-medium text-red-400">
              {critical ?? "—"}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md">
        <CardContent className="p-3 pt-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            Watch (1e-6–1e-4)
          </p>
          {flaggedLoading && !flagged ? (
            <Skeleton className="mt-1 h-6 w-10" />
          ) : (
            <p className="mt-1 font-mono text-xl font-medium text-amber-400">
              {watch ?? "—"}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md">
        <CardContent className="p-3 pt-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            Newest TLE
          </p>
          {summaryLoading && !summary ? (
            <Skeleton className="mt-1 h-6 w-24" />
          ) : (
            <p className="mt-1 font-mono text-sm leading-tight text-slate-300">
              {formatSecondsAgo(summary?.newest_tle_epoch ?? null)}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="col-span-2 border-cyan-500/20 bg-[rgba(8,15,30,0.65)] shadow-lg shadow-black/40 backdrop-blur-md md:col-span-1">
        <CardContent className="p-3 pt-3">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            Space weather
          </p>
          {spaceLoading && !spaceWeather ? (
            <Skeleton className="mt-1 h-6 w-28" />
          ) : (
            <p
              className={`mt-1 font-mono text-sm font-medium ${stormTone(spaceWeather?.geomag_storm_level ?? "")}`}
            >
              Kp {spaceWeather?.kp_index?.toFixed(2) ?? "—"} ·{" "}
              {spaceWeather?.geomag_storm_level ?? "—"}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
