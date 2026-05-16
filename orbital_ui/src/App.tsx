import * as React from "react";
import {
  QueryClient,
  QueryClientProvider,
  keepPreviousData,
  useQuery,
} from "@tanstack/react-query";
import { Toaster, toast } from "sonner";
import { ConjunctionDetailView } from "@/components/ConjunctionDetailView";
import { ApproverView } from "@/components/ApproverView";
import { MemoryLogView } from "@/components/MemoryLogView";
import { GlobeView, type GlobeViewHandle } from "@/components/GlobeView";
import {
  ACTIVE_SECTOR_ID,
  getCatalogPositions,
  getCatalogSummary,
  getConjunctionEvent,
  getFlaggedConjunctions,
  getSectorCurrent,
} from "@/lib/api";
import { conjunctionCameraTarget } from "@/lib/conjunctionCamera";
import type { SatellitePosition } from "@/lib/types";
import { toFlaggedConjunction } from "@/lib/types";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

const AGENT_LOGS = [
  { type: "thought", text: "Monitoring 847 objects, 23 in elevated-risk watch, no new flags in last 30 seconds.", time: "14:31:02" },
  { type: "tool", text: "get_flagged_conjunctions(since=-30s, min_pc=1e-6) → 0 new", time: "14:31:02" },
  { type: "thought", text: "Monitoring 847 objects, 23 in elevated-risk watch, no new flags in last 30 seconds.", time: "14:30:32" },
  { type: "tool", text: "get_space_weather() → Kp 4.2, minor storm G1, drag +8%", time: "14:30:00" },
  { type: "thought", text: "All assets nominal. Next scheduled re-screen in 6 hours for 4 watch-list events.", time: "14:29:30" }
];

function Dashboard(): React.ReactElement {
  const [showOrbits, setShowOrbits] = React.useState(false);
  const [showLabels, setShowLabels] = React.useState(false);
  const [threatsOnly, setThreatsOnly] = React.useState(false);
  const [isPaused, setIsPaused] = React.useState(false);
  const [isExpanded, setIsExpanded] = React.useState(false);
  const [currentView, setCurrentView] = React.useState<"dashboard" | "approver" | "memory">("dashboard");
  const [selectedEventId, setSelectedEventId] = React.useState<string | null>(null);
  const [lockedEventId, setLockedEventId] = React.useState<string | null>(null);
  const [selectedPoint, setSelectedPoint] = React.useState<SatellitePosition | null>(null);
  const globeRef = React.useRef<GlobeViewHandle | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["catalog-summary"],
    queryFn: getCatalogSummary,
    refetchInterval: 60_000,
  });

  const flaggedQuery = useQuery({
    queryKey: ["conjunctions-flagged"],
    queryFn: getFlaggedConjunctions,
    refetchInterval: 10_000,
    enabled: !isPaused,
  });

  const sectorQuery = useQuery({
    queryKey: ["sector-current", ACTIVE_SECTOR_ID],
    queryFn: () => getSectorCurrent(ACTIVE_SECTOR_ID),
    refetchInterval: 60_000,
  });

  const positionsQuery = useQuery({
    queryKey: ["catalog-positions", 500, ACTIVE_SECTOR_ID, showOrbits],
    queryFn: () => getCatalogPositions({ limit: 500, sector: ACTIVE_SECTOR_ID, includePaths: showOrbits }),
    refetchInterval: 5_000,
    placeholderData: keepPreviousData,
    enabled: !isPaused,
  });

  const points = positionsQuery.data ?? [];
  const conjunctions = flaggedQuery.data?.conjunctions ?? [];
  const totalMonitored = summaryQuery.data?.total_objects ?? 847;

  const actionReq = conjunctions.filter((c) => c.pc_band === "action").length;
  const underWatch = conjunctions.filter((c) => c.pc_band === "watch").length;

  const conjunctionStatusMap = React.useMemo(() => {
    const map = new Map<number, string>();
    for (const c of conjunctions) {
      map.set(c.obj1.norad_id, c.pc_band);
      map.set(c.obj2.norad_id, c.pc_band);
    }
    return map;
  }, [conjunctions]);

  const renderedPoints = React.useMemo(() => {
    if (threatsOnly) {
      return points.filter((p) => conjunctionStatusMap.has(p.norad_id));
    }
    return points;
  }, [points, threatsOnly, conjunctionStatusMap]);

  const sectorBand = React.useMemo(
    () =>
      sectorQuery.data !== undefined
        ? {
            altitude_min_km: sectorQuery.data.sector.altitude_min_km,
            altitude_max_km: sectorQuery.data.sector.altitude_max_km,
          }
        : null,
    [sectorQuery.data?.sector.altitude_min_km, sectorQuery.data?.sector.altitude_max_km],
  );

  const eventFromQueue = React.useMemo(
    () => (selectedEventId ? conjunctions.find((c) => c.id === selectedEventId) ?? null : null),
    [conjunctions, selectedEventId],
  );

  const persistedEventQuery = useQuery({
    queryKey: ["conjunction-event", selectedEventId],
    queryFn: () => getConjunctionEvent(selectedEventId!),
    enabled: Boolean(selectedEventId) && !eventFromQueue,
  });

  const selectedEvent = React.useMemo(() => {
    if (!selectedEventId) return null;
    if (eventFromQueue) return eventFromQueue;
    if (persistedEventQuery.data) return toFlaggedConjunction(persistedEventQuery.data);
    return null;
  }, [selectedEventId, eventFromQueue, persistedEventQuery.data]);

  const detailLoading =
    Boolean(selectedEventId) && !eventFromQueue && persistedEventQuery.isLoading;
  const detailFetchError =
    Boolean(selectedEventId) && !eventFromQueue && persistedEventQuery.isError;

  const handlePointClick = React.useCallback(
    (p: SatellitePosition) => {
      setSelectedPoint(p);
    },
    []
  );

  const handleViewEvent = React.useCallback(
    (p: SatellitePosition) => {
      const event = conjunctions.find((c) => c.obj1.norad_id === p.norad_id || c.obj2.norad_id === p.norad_id);
      if (event) {
        setSelectedEventId(event.id);
        setIsExpanded(false);
        setSelectedPoint(null);
      } else {
        toast(`Satellite ${p.name} selected. No active conjunctions.`);
      }
    },
    [conjunctions]
  );

  if (currentView === "approver") {
    return <ApproverView onNavigate={setCurrentView} />;
  }

  if (currentView === "memory") {
    return (
      <MemoryLogView
        onNavigate={setCurrentView}
        onSelectEvent={(eventId) => setSelectedEventId(eventId)}
      />
    );
  }

  if (detailLoading) {
    return (
      <div className="min-h-screen bg-[#060b14] flex items-center justify-center text-slate-400 font-mono text-sm">
        Loading conjunction event…
      </div>
    );
  }

  if (detailFetchError) {
    return (
      <div className="min-h-screen bg-[#060b14] flex flex-col items-center justify-center gap-4 text-slate-200 font-mono p-6">
        <p className="text-red-400">Could not load event from persistence.</p>
        <button
          type="button"
          className="text-[#378add] underline"
          onClick={() => setSelectedEventId(null)}
        >
          Back
        </button>
      </div>
    );
  }

  if (selectedEvent) {
    return <ConjunctionDetailView event={selectedEvent} onBack={() => setSelectedEventId(null)} />;
  }

  return (
    <div className="flex flex-col min-h-screen bg-[#060b14] text-slate-200 font-mono text-sm p-4 gap-[10px]">
      
      {/* NavBar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="font-bold tracking-widest text-slate-100">ORBITAL</span>
        </div>
        <div className="flex gap-6 text-slate-400">
          <span className="text-white cursor-pointer" onClick={() => setCurrentView("dashboard")}>Dashboard</span>
          <span className="cursor-pointer hover:text-slate-200" onClick={() => setCurrentView("approver")}>Approver</span>
          <span className="cursor-pointer hover:text-slate-200" onClick={() => setCurrentView("memory")}>Memory</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-500 text-xs font-semibold">IDLE</span>
          <span className="text-slate-400 text-xs">{totalMonitored} objects monitored</span>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-4 gap-[10px]">
        <div className="bg-[rgba(239,68,68,0.05)] border border-[rgba(239,68,68,0.1)] rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Action required</span>
          <span className="text-2xl text-red-400">{actionReq}</span>
        </div>
        <div className="bg-[rgba(245,158,11,0.05)] border border-[rgba(245,158,11,0.1)] rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Under watch</span>
          <span className="text-2xl text-amber-400">{underWatch}</span>
        </div>
        <div className="bg-[rgba(34,197,94,0.05)] border border-[rgba(34,197,94,0.1)] rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Dismissed today</span>
          <span className="text-2xl text-green-400">14</span>
        </div>
        <div className="bg-[#0d1a2d] border border-mission-border rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Pending approval</span>
          <span className="text-2xl text-slate-200">1</span>
        </div>
      </div>

      {/* Main Area Grid */}
      <div className="flex gap-[10px] w-full">
        {/* Left Column 55% */}
        <div className="w-[55%] border border-mission-border bg-mission-panel rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center">
            <span>Live orbit view</span>
            <div className="flex gap-2 items-center">
              <span className="text-slate-500 text-xs">click satellite to select</span>
              <button onClick={() => setIsExpanded(true)} className="text-[#7a9ab0] hover:text-white" title="Expand to fullscreen">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                </svg>
              </button>
            </div>
          </div>
          <div className={isExpanded ? "fixed inset-0 z-50 bg-[#060b14] flex flex-col" : "relative h-[320px] bg-[#060b14] overflow-hidden flex flex-col"}>
            {isExpanded && (
              <div className="p-4 flex justify-between items-center bg-mission-panel border-b border-mission-border shrink-0 absolute top-0 left-0 right-0 z-10">
                <span className="font-bold text-lg text-slate-200">Expanded Orbit View</span>
                <button onClick={() => setIsExpanded(false)} className="px-3 py-1 bg-red-500/20 text-red-400 hover:bg-red-500/40 rounded border border-red-500/50">
                  Exit Full Screen
                </button>
              </div>
            )}
            <div className="flex-1 relative">
              <div className="absolute inset-0 flex items-center justify-center">
                <GlobeView
                  ref={globeRef}
                  points={renderedPoints}
                  conjunctionStatusMap={conjunctionStatusMap}
                  intenseNorads={new Set()}
                  sectorBand={sectorBand}
                  showOrbits={showOrbits}
                  showLabels={showLabels}
                  autoRotate={!isPaused}
                  selectedPoint={selectedPoint}
                  onPointClick={handlePointClick}
                  onClosePoint={() => setSelectedPoint(null)}
                  onViewEvent={handleViewEvent}
                />
              </div>
            </div>
          </div>
          <div className="px-[14px] py-[12px] flex gap-2 border-t border-mission-border bg-mission-panel mt-auto items-center">
            <button
              className={`px-3 py-1.5 text-xs border rounded font-bold flex items-center gap-2 transition-colors ${isPaused ? 'bg-amber-500/20 border-amber-500/50 text-amber-500' : 'bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.1)] text-[#7a9ab0] hover:bg-[rgba(255,255,255,0.08)]'}`}
              onClick={() => setIsPaused(!isPaused)}
            >
              {isPaused ? "▶ Play" : "⏸ Pause"}
            </button>
            <div className="w-px h-4 bg-mission-border mx-1"></div>
            <button
              className={`px-3 py-1.5 text-xs border rounded font-bold transition-colors ${threatsOnly ? 'bg-red-500/20 border-red-500/50 text-red-400' : 'bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.1)] text-[#7a9ab0] hover:bg-[rgba(255,255,255,0.08)]'}`}
              onClick={() => {
                const nextThreatsOnly = !threatsOnly;
                setThreatsOnly(nextThreatsOnly);
                if (!nextThreatsOnly) {
                  setShowOrbits(false);
                  setShowLabels(false);
                }
              }}
            >
              Threats only
            </button>
            {threatsOnly && (
              <>
                <button
                  className={`px-3 py-1.5 text-xs border rounded font-bold transition-colors ${showOrbits ? 'bg-[#378add]/20 border-[#378add]/50 text-[#378add]' : 'bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.1)] text-[#7a9ab0] hover:bg-[rgba(255,255,255,0.08)]'}`}
                  onClick={() => setShowOrbits(!showOrbits)}
                >
                  Orbits
                </button>
                <button
                  className={`px-3 py-1.5 text-xs border rounded font-bold transition-colors ${showLabels ? 'bg-[#378add]/20 border-[#378add]/50 text-[#378add]' : 'bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.1)] text-[#7a9ab0] hover:bg-[rgba(255,255,255,0.08)]'}`}
                  onClick={() => setShowLabels(!showLabels)}
                >
                  Labels
                </button>
              </>
            )}
            {lockedEventId && (
              <button
                className="ml-auto px-3 py-1.5 text-xs border border-green-500/50 bg-green-500/20 text-green-400 hover:bg-green-500/30 rounded font-bold transition-colors"
                onClick={() => {
                  setLockedEventId(null);
                  globeRef.current?.resetCamera();
                }}
              >
                Fit all
              </button>
            )}
          </div>
        </div>

        {/* Right Column 45% */}
        <div className="w-[45%] border border-mission-border bg-mission-panel rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center">
            <span>Conjunction queue</span>
            <span className="text-slate-500 text-xs">sorted by Pc ↓</span>
          </div>
          <div className="flex flex-col flex-1">
            {/* Header row */}
            <div className="flex px-[14px] py-2 bg-[#060b14] text-[#3a5060] text-[10px] uppercase border-b border-[rgba(255,255,255,0.06)] shrink-0">
              <div className="w-[42%]">Object pair</div>
              <div className="w-[18%]">TCA</div>
              <div className="w-[22%]">Pc</div>
              <div className="w-[18%]">Status</div>
            </div>
            {/* Rows */}
            <div className="flex-1 overflow-y-auto max-h-[290px]">
              {conjunctions.map((c) => {
                const isUrgent = c.pc_band === "action";
                const isWatch = c.pc_band === "watch";
                const isLow = c.pc_band === "noise";

                return (
                  <div
                    key={c.id}
                    onClick={() => {
                      setLockedEventId(c.id);
                      const aim = conjunctionCameraTarget(c);
                      if (aim) {
                        globeRef.current?.flyTo(aim.lat, aim.lon, aim.alt);
                      } else {
                        globeRef.current?.flyToMidpoint(c.obj1.norad_id, c.obj2.norad_id);
                      }
                    }}
                    className={`flex items-center px-[14px] h-[40px] border-b border-[rgba(255,255,255,0.06)] cursor-pointer hover:bg-white/5 transition-colors ${
                      isUrgent ? "bg-[rgba(239,68,68,0.06)]" : ""
                    } ${isLow ? "opacity-50" : ""} ${lockedEventId === c.id ? "bg-white/10" : ""}`}
                  >
                    <div className="w-[42%] flex items-center gap-2 truncate pr-2">
                      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isUrgent ? "bg-red-500" : isWatch ? "bg-amber-500" : "bg-green-500"}`} />
                      <div className="truncate text-xs">
                        <span className={isUrgent ? "font-bold text-slate-200" : "text-slate-200"}>{c.obj1.name}</span>
                        <span className="text-slate-500 ml-1">↔ {c.obj2.name}</span>
                      </div>
                    </div>
                    <div className="w-[18%] text-xs text-slate-300 truncate pr-2">{c.tca.split("T")[1]?.slice(0, 5) || c.tca}</div>
                    <div className={`w-[22%] text-xs truncate pr-2 ${isUrgent ? "text-red-400" : isWatch ? "text-amber-400" : "text-slate-500"}`}>
                      {c.pc.toExponential(1)}
                    </div>
                    <div className="w-[18%] flex items-center justify-between">
                      <span className={`px-2 py-0.5 rounded-full text-[9px] font-semibold tracking-wider ${
                        isUrgent ? "bg-red-500/20 text-red-400" :
                        isWatch ? "bg-amber-500/20 text-amber-400" : "bg-green-500/10 text-green-500"
                      }`}>
                        {isUrgent ? "URGENT" : isWatch ? "WATCH" : "LOW"}
                      </span>
                      {lockedEventId === c.id && (
                        <button 
                          onClick={(e) => { e.stopPropagation(); setSelectedEventId(c.id); }}
                          className="px-2 py-1 bg-[#378add]/20 text-[#378add] hover:bg-[#378add]/40 border border-[#378add]/50 rounded text-[10px] font-bold"
                        >
                          Details ➔
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {/* Footer row */}
            <div className="py-2 mt-auto text-center text-[#3a5060] text-[10px] shrink-0">
              + 20 more monitored objects
            </div>
          </div>
        </div>
      </div>

      {/* Agent Activity Panel */}
      <div className="mt-auto border border-mission-border bg-mission-panel rounded-lg flex flex-col overflow-hidden h-[180px]">
        <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center shrink-0">
          <span>Agent activity</span>
          <span className="px-2 py-0.5 rounded bg-green-500/20 text-green-500 text-xs font-semibold">IDLE</span>
        </div>
        <div className="flex flex-col p-[14px] py-2 overflow-hidden gap-3">
          {AGENT_LOGS.map((log, i) => (
            <div key={i} className="flex gap-3 items-start text-xs">
              <div className="mt-0.5 shrink-0">
                {log.type === "thought" ? (
                  <svg className="w-3.5 h-3.5 text-[#7a9ab0]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5 text-[#f59e0b]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v8l9-11h-7z" />
                  </svg>
                )}
              </div>
              <div className="flex-1">
                {log.type === "tool" ? (
                  <>
                    <span className="text-amber-500">tool_call: </span>
                    <span className="text-[#7a9ab0]">{log.text}</span>
                  </>
                ) : (
                  <span className="text-[#c8d6e8]">{log.text}</span>
                )}
              </div>
              <div className="text-[9px] text-[#3a5060] shrink-0">{log.time}</div>
            </div>
          ))}
        </div>
      </div>
      
    </div>
  );
}

export default function App(): React.ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
      <Toaster theme="dark" position="top-right" />
    </QueryClientProvider>
  );
}
