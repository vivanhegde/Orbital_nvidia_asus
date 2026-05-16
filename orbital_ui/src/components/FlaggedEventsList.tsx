import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { FlaggedConjunction } from "@/lib/types";
import {
  formatPcOneSigFig,
  formatUntilTca,
  formatUtcAbsolute,
} from "@/lib/time";
import { cn } from "@/lib/utils";

function bandStripe(band: FlaggedConjunction["pc_band"]): string {
  if (band === "action") return "bg-red-500";
  if (band === "watch") return "bg-amber-500";
  return "bg-slate-600";
}

export interface FlaggedEventsListProps {
  items: FlaggedConjunction[] | undefined;
  loading: boolean;
  onSelect: (c: FlaggedConjunction) => void;
  /** Preview detail in the Catalog column (debounced clear is handled in App). */
  onPreviewHover?: (c: FlaggedConjunction | null) => void;
  filterNoradId?: number | null;
  highlightEventId?: string | null;
  className?: string;
}

function FlaggedEventRow({
  conjunction: c,
  onSelect,
  onPreviewHover,
  highlightEventId,
  setCardRef,
}: {
  conjunction: FlaggedConjunction;
  onSelect: (c: FlaggedConjunction) => void;
  onPreviewHover?: (c: FlaggedConjunction | null) => void;
  highlightEventId?: string | null;
  setCardRef: (id: string, el: HTMLButtonElement | null) => void;
}): React.ReactElement {
  return (
    <button
      ref={(el) => {
        setCardRef(c.id, el);
      }}
      type="button"
      onClick={() => {
        onSelect(c);
      }}
      onMouseEnter={() => {
        onPreviewHover?.(c);
      }}
      onMouseLeave={() => {
        onPreviewHover?.(null);
      }}
      className={cn(
        "missions-event-card w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-cyan-500",
        highlightEventId === c.id &&
          "missions-highlight-pulse rounded-lg ring-2 ring-cyan-400/90 ring-offset-2 ring-offset-slate-950/0",
      )}
    >
      <Card className="relative overflow-hidden border-cyan-500/20 bg-[rgba(8,15,30,0.72)] shadow-lg shadow-black/40 backdrop-blur-md transition-colors hover:border-cyan-600/50">
        <div
          className={`absolute left-0 top-0 h-full w-1 ${bandStripe(c.pc_band)}`}
        />
        <div className="relative p-3 pl-3">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate font-mono text-sm text-slate-100">
              {c.obj1.name} <span className="text-slate-500">vs</span>{" "}
              {c.obj2.name}
            </p>
            <Badge
              variant={
                c.pc_band === "action"
                  ? "action"
                  : c.pc_band === "watch"
                    ? "watch"
                    : "noise"
              }
              className="shrink-0"
            >
              {c.pc_band}
            </Badge>
          </div>
          <p className="mt-1 font-mono text-xs text-cyan-400/90">
            TCA {formatUntilTca(c.tca)} ·{" "}
            <span className="text-slate-400">
              {formatUtcAbsolute(c.tca)}
            </span>
          </p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-slate-400">
            <span>Miss {c.miss_distance_km.toFixed(1)} km</span>
            <span>Pc {formatPcOneSigFig(c.pc)}</span>
            <span>Δv {c.relative_velocity_km_s.toFixed(1)} km/s</span>
          </div>
        </div>
      </Card>
    </button>
  );
}

export function FlaggedEventsList({
  items,
  loading,
  onSelect,
  onPreviewHover,
  filterNoradId,
  highlightEventId,
  className,
}: FlaggedEventsListProps): React.ReactElement {
  const cardRefs = React.useRef<Record<string, HTMLButtonElement | null>>({});

  const setCardRef = React.useCallback(
    (id: string, el: HTMLButtonElement | null) => {
      cardRefs.current[id] = el;
    },
    [],
  );

  React.useEffect(() => {
    if (!highlightEventId) return;
    const el = cardRefs.current[highlightEventId];
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [highlightEventId]);
  if (loading && !items) {
    return (
      <div className="flex flex-col gap-2 p-2">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  const top = React.useMemo(() => {
    let xs = items ?? [];
    if (filterNoradId != null) {
      xs = xs.filter(
        (c) =>
          c.obj1.norad_id === filterNoradId || c.obj2.norad_id === filterNoradId,
      );
    }
    return xs.slice(0, 50);
  }, [items, filterNoradId]);

  if (top.length === 0) {
    if (filterNoradId != null && (items?.length ?? 0) > 0) {
      return (
        <div
          className={cn(
            "rounded-lg border border-cyan-500/20 bg-[rgba(8,15,30,0.65)] p-6 text-center font-mono text-sm text-slate-500 shadow-lg shadow-black/40 backdrop-blur-md",
            className,
          )}
        >
          No flagged conjunctions involving NORAD {filterNoradId}.
        </div>
      );
    }
    return (
      <div
        className={cn(
          "rounded-lg border border-dashed border-cyan-500/30 bg-[rgba(8,15,30,0.55)] p-6 text-center text-sm text-slate-500 shadow-lg backdrop-blur-md",
          className,
        )}
      >
        No flagged conjunctions in cache yet. Screening runs every 60s or use
        Refresh.
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex max-h-[60vh] flex-col gap-2 overflow-y-auto pr-1",
        className,
      )}
    >
      {top.map((c) => (
        <FlaggedEventRow
          key={c.id}
          conjunction={c}
          onSelect={onSelect}
          onPreviewHover={onPreviewHover}
          highlightEventId={highlightEventId}
          setCardRef={setCardRef}
        />
      ))}
    </div>
  );
}
