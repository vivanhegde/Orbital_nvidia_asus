import * as React from "react";
import { useQueries } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { getCatalogObject } from "@/lib/api";
import type { CatalogObjectResponse, FlaggedConjunction } from "@/lib/types";
import { formatPcOneSigFig, formatUtcAbsolute } from "@/lib/time";
import { cn } from "@/lib/utils";

function bandLabel(band: FlaggedConjunction["pc_band"]): string {
  if (band === "action") return "Action";
  if (band === "watch") return "Watch";
  return "Noise";
}

function thresholdContext(
  pc: number,
  band: FlaggedConjunction["pc_band"],
): string {
  const action = 1e-4;
  if (band === "action") {
    return `Action threshold is 1e-4; this event is ${(pc / action).toFixed(1)}× above.`;
  }
  if (band === "watch") {
    return `Action threshold is 1e-4; this event is ${(pc / action).toExponential(1)} of threshold.`;
  }
  return `Below watch band (1e-6); nominal noise floor for TLE covariances.`;
}

export interface ConjunctionDetailPanelProps {
  item: FlaggedConjunction;
  /** Load heavy catalog lookups only while this panel is visible. */
  fetchEnabled: boolean;
  className?: string;
  /**
   * NORAD IDs that currently have a dot on the globe (sector positions feed).
   * When omitted or while loading, live coverage hints are hidden.
   */
  liveGlobeNoradIds?: ReadonlySet<number>;
  /** When true, suppress globe coverage messaging until positions have loaded. */
  liveGlobePositionsLoading?: boolean;
}

export function ConjunctionDetailPanel({
  item,
  fetchEnabled,
  className,
  liveGlobeNoradIds,
  liveGlobePositionsLoading = false,
}: ConjunctionDetailPanelProps): React.ReactElement {
  const ids = [item.obj1.norad_id, item.obj2.norad_id] as const;

  const missingFromGlobe = React.useMemo(() => {
    if (liveGlobePositionsLoading || liveGlobeNoradIds === undefined) {
      return [];
    }
    const out: { norad_id: number; name: string }[] = [];
    if (!liveGlobeNoradIds.has(item.obj1.norad_id)) {
      out.push({ norad_id: item.obj1.norad_id, name: item.obj1.name });
    }
    if (!liveGlobeNoradIds.has(item.obj2.norad_id)) {
      out.push({ norad_id: item.obj2.norad_id, name: item.obj2.name });
    }
    return out;
  }, [
    item.obj1.norad_id,
    item.obj1.name,
    item.obj2.norad_id,
    item.obj2.name,
    liveGlobeNoradIds,
    liveGlobePositionsLoading,
  ]);

  const results = useQueries({
    queries: [
      {
        queryKey: ["catalog-object", ids[0]],
        queryFn: () => getCatalogObject(ids[0]),
        enabled: fetchEnabled && ids[0] > 0,
      },
      {
        queryKey: ["catalog-object", ids[1]],
        queryFn: () => getCatalogObject(ids[1]),
        enabled: fetchEnabled && ids[1] > 0,
      },
    ],
  });

  const d1: CatalogObjectResponse | undefined = results[0]?.data;
  const d2: CatalogObjectResponse | undefined = results[1]?.data;

  return (
    <div
      className={cn(
        "max-h-[min(70vh,520px)] overflow-y-auto p-4 font-mono text-sm",
        className,
      )}
    >
      <div className="border-b border-mission-border pb-3">
        <p className="text-xs uppercase tracking-wide text-slate-500">
          Conjunction
        </p>
        <p className="mt-1 text-base text-slate-100">
          {item.obj1.name}{" "}
          <span className="text-slate-500">vs</span> {item.obj2.name}
        </p>
        <p className="mt-1 text-xs text-slate-500">{item.id.slice(0, 8)}…</p>
      </div>

      {missingFromGlobe.length > 0 ? (
        <div className="mx-4 mt-3 rounded border border-amber-500/35 bg-amber-500/10 px-3 py-2.5 text-[11px] leading-snug text-amber-100/95">
          <p className="font-mono uppercase tracking-wide text-amber-200/90">
            Live globe coverage
          </p>
          <p className="mt-1 text-amber-100/85">
            Dots only show objects returned by the sector position poll (500 max).
            No live dot this poll for:{" "}
            {missingFromGlobe.map((m, i) => (
              <span key={m.norad_id}>
                {i > 0 ? ", " : ""}
                <span className="whitespace-nowrap">
                  {m.name}{" "}
                  <span className="text-amber-200/70">(NORAD {m.norad_id})</span>
                </span>
              </span>
            ))}
            . Common causes: propagation skipped that object at the current
            epoch, or it is outside the returned batch.
          </p>
        </div>
      ) : null}

      <div className="animate-missions-detail-body space-y-5 pt-4">
        <section>
          <h4 className="text-xs uppercase tracking-wide text-slate-500">
            Objects
          </h4>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {[item.obj1, item.obj2].map((o, idx) => {
              const d = idx === 0 ? d1 : d2;
              const q = idx === 0 ? results[0] : results[1];
              const onGlobe =
                !liveGlobePositionsLoading &&
                liveGlobeNoradIds !== undefined &&
                liveGlobeNoradIds.has(o.norad_id);
              const globeUnknown =
                liveGlobePositionsLoading || liveGlobeNoradIds === undefined;
              return (
                <div
                  key={o.norad_id}
                  className="rounded border border-mission-border bg-slate-900/50 p-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-slate-100">{o.name}</p>
                    {!globeUnknown ? (
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          onGlobe
                            ? "bg-emerald-500/15 text-emerald-300/90"
                            : "bg-slate-700/80 text-slate-400",
                        )}
                        title={
                          onGlobe
                            ? "This NORAD is in the current globe positions feed"
                            : "No dot on the globe for this NORAD in the current feed"
                        }
                      >
                        {onGlobe ? "On globe" : "No dot"}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    NORAD {o.norad_id} · SATCAT {o.type}
                  </p>
                  {d?.tle ? (
                    <p className="mt-1 text-xs text-slate-500">
                      Group {d.tle.source_group}
                    </p>
                  ) : q?.isPending ? (
                    <p className="mt-1 text-xs text-slate-600">Loading…</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h4 className="text-xs uppercase tracking-wide text-slate-500">
            Encounter
          </h4>
          <ul className="mt-2 space-y-1 text-slate-300">
            <li>TCA {formatUtcAbsolute(item.tca)}</li>
            <li>Miss distance {item.miss_distance_km.toFixed(1)} km</li>
            <li>
              Relative velocity {item.relative_velocity_km_s.toFixed(1)} km/s
            </li>
            <li>Detected {formatUtcAbsolute(item.detected_at)}</li>
          </ul>
        </section>

        <section>
          <h4 className="text-xs uppercase tracking-wide text-slate-500">
            Probability
          </h4>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-lg text-cyan-300">
              Pc {formatPcOneSigFig(item.pc)}
            </span>
            <Badge
              variant={
                item.pc_band === "action"
                  ? "action"
                  : item.pc_band === "watch"
                    ? "watch"
                    : "noise"
              }
            >
              {bandLabel(item.pc_band)}
            </Badge>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">
            {thresholdContext(item.pc, item.pc_band)}
          </p>
        </section>

        <section className="rounded border border-dashed border-slate-700 p-3">
          <h4 className="text-xs uppercase tracking-wide text-slate-500">
            Agent verdict
          </h4>
          <p className="mt-2 text-slate-500">No analysis yet</p>
        </section>

        <p className="border-t border-mission-border pt-3 text-center text-[10px] text-slate-500">
          Click row to fly the globe to TCA geometry
        </p>
      </div>
    </div>
  );
}
