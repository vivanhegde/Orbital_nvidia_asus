import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { AgentReasoningStream } from "./AgentReasoningStream";
import type { FlaggedConjunction } from "@/lib/types";
import { getCatalogObject } from "@/lib/api";
import { formatUtcAbsolute } from "@/lib/time";
import {
  inferManeuverable,
  patternSummary,
  syntheticAssetProfile,
  syntheticPattern,
  syntheticPcHistory,
  syntheticReasoningForEvent,
} from "@/lib/syntheticPc";

function hoursAgo(iso: string | undefined): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return null;
  return ms / 3_600_000;
}

function formatTleAge(hours: number | null): string {
  if (hours == null) return "—";
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

export interface ConjunctionDetailViewProps {
  event: FlaggedConjunction;
  onBack: () => void;
}

export function ConjunctionDetailView({ event, onBack }: ConjunctionDetailViewProps) {
  const isUrgent = event.pc_band === "action";
  const badgeText = isUrgent ? "URGENT" : event.pc_band === "watch" ? "WATCH" : "LOW";
  const badgeColor = isUrgent
    ? "bg-red-500/20 text-red-400"
    : event.pc_band === "watch"
      ? "bg-amber-500/20 text-amber-400"
      : "bg-green-500/10 text-green-500";

  // Synthetic 7-day Pc history. Each event_id gets a deterministic pattern
  // (declining / rising / storm-spike / oscillating / maneuver-resolved) so
  // the graph stays stable across reloads but differs across events.
  // Pulled from React.useMemo so we don't regenerate on every render.
  const snaps = React.useMemo(() => syntheticPcHistory(event.id), [event.id]);
  const pattern = React.useMemo(() => syntheticPattern(event.id), [event.id]);
  const syntheticEvents = React.useMemo(
    () => syntheticReasoningForEvent(event.id),
    [event.id],
  );

  const historyPoints = snaps.map((s) => ({
    time: formatUtcAbsolute(s.snapshot_at).slice(5, 16),
    pc: Math.max(s.pc, 1e-12),
  }));

  const lastSnap = snaps.length > 0 ? snaps[snaps.length - 1] : null;
  const sw = lastSnap?.space_weather_snapshot;

  // Real TLE data per object (epoch → derive age in hours).
  const obj1Query = useQuery({
    queryKey: ["catalog-object", event.obj1.norad_id],
    queryFn: () => getCatalogObject(event.obj1.norad_id),
    staleTime: 60_000,
  });
  const obj2Query = useQuery({
    queryKey: ["catalog-object", event.obj2.norad_id],
    queryFn: () => getCatalogObject(event.obj2.norad_id),
    staleTime: 60_000,
  });
  const tleAge1 = hoursAgo(obj1Query.data?.tle?.epoch);
  const tleAge2 = hoursAgo(obj2Query.data?.tle?.epoch);

  // Maneuverability + per-asset synthetic profile (Δv budget, fuel %, mass, RCS, …).
  const obj1Maneuverable = React.useMemo(
    () => inferManeuverable(event.obj1.type),
    [event.obj1.type],
  );
  const obj2Maneuverable = React.useMemo(
    () => inferManeuverable(event.obj2.type),
    [event.obj2.type],
  );
  const obj1Profile = React.useMemo(
    () => syntheticAssetProfile(event.obj1.norad_id, event.obj1.name, obj1Maneuverable),
    [event.obj1.norad_id, event.obj1.name, obj1Maneuverable],
  );
  const obj2Profile = React.useMemo(
    () => syntheticAssetProfile(event.obj2.norad_id, event.obj2.name, obj2Maneuverable),
    [event.obj2.norad_id, event.obj2.name, obj2Maneuverable],
  );

  // Primary asset = whichever is maneuverable (if exactly one). Otherwise obj1.
  const primaryProfile = obj1Maneuverable && !obj2Maneuverable
    ? obj1Profile
    : !obj1Maneuverable && obj2Maneuverable
      ? obj2Profile
      : obj1Profile;

  return (
    <div className="flex flex-col min-h-screen bg-[#060b14] text-slate-200 font-mono text-sm p-4 gap-[10px]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={onBack}
            className="text-slate-400 hover:text-white flex items-center gap-1 cursor-pointer transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Dashboard
          </button>
          <span className="text-slate-600">/</span>
          <span className="font-bold text-slate-100">
            {event.obj1.name} ↔ {event.obj2.name}
          </span>
        </div>
        <div>
          <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-500 text-xs font-semibold tracking-wider">
            INVESTIGATING
          </span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-[10px]">
        <div className="bg-mission-panel border border-mission-border rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Primary Asset</span>
          <span className="text-xl text-slate-200 truncate">{event.obj1.name}</span>
        </div>
        <div className="bg-mission-panel border border-mission-border rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Δv budget (primary)</span>
          <span className="text-xl text-cyan-400">
            {primaryProfile.delta_v_remaining_mps > 0
              ? `${primaryProfile.delta_v_remaining_mps.toFixed(1)} m/s`
              : "n/a"}
            <span className="text-[10px] text-slate-500 ml-2">
              {primaryProfile.delta_v_budget_mps > 0
                ? `of ${primaryProfile.delta_v_budget_mps.toFixed(0)}`
                : ""}
            </span>
          </span>
        </div>
        <div className="bg-mission-panel border border-mission-border rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">TLE age (obj1 / obj2)</span>
          <span className="text-xl text-slate-200">
            {formatTleAge(tleAge1)} / {formatTleAge(tleAge2)}
          </span>
        </div>
        <div className="bg-[rgba(245,158,11,0.05)] border border-[rgba(245,158,11,0.1)] rounded-lg p-[10px] px-3 flex flex-col justify-between h-[80px]">
          <span className="text-slate-400 text-xs">Kp index</span>
          <span className="text-xl text-amber-400">
            {sw ? `${sw.kp_index.toFixed(1)} (${sw.geomag_storm_level})` : "—"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-[10px] min-h-[220px]">
        <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center gap-3">
            <span>Pc History (7d)</span>
            <span className="text-[10px] text-slate-500 truncate text-right" title={patternSummary(pattern)}>
              {patternSummary(pattern)}
            </span>
          </div>
          <div className="flex-1 p-4 relative min-h-[180px]">
            {snaps.length === 0 ? (
              <div className="text-slate-500 text-xs leading-relaxed p-2">
                Building history…
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historyPoints} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorPc" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" stroke="#3a5060" fontSize={10} tickMargin={8} />
                  <YAxis
                    scale="log"
                    domain={["auto", "auto"]}
                    stroke="#3a5060"
                    fontSize={10}
                    tickFormatter={(val: number) => val.toExponential(0)}
                    width={45}
                  />
                  <ReferenceLine y={1e-4} stroke="#ef4444" strokeDasharray="3 3" />
                  <Area
                    type="monotone"
                    dataKey="pc"
                    stroke="#ef4444"
                    fillOpacity={1}
                    fill="url(#colorPc)"
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)]">
            <span>Space Weather — at snapshot</span>
          </div>
          <div className="flex-1 p-5 flex flex-col justify-center gap-5">
            {!lastSnap ? (
              <p className="text-slate-500 text-xs">No persistence snapshot yet.</p>
            ) : (
              <>
                <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-2">
                  <span className="text-slate-400">Snapshot time (UTC)</span>
                  <span className="text-slate-200 text-xs">{formatUtcAbsolute(lastSnap.snapshot_at)}</span>
                </div>
                <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-2">
                  <span className="text-slate-400">Kp Index</span>
                  <span className="text-amber-400 font-bold text-base">
                    {lastSnap.kp_index != null ? lastSnap.kp_index.toFixed(2) : "—"}
                  </span>
                </div>
                <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-2">
                  <span className="text-slate-400">Storm Level</span>
                  <span className="text-amber-400 text-base">{sw?.geomag_storm_level ?? "—"}</span>
                </div>
                <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-2">
                  <span className="text-slate-400">X-ray class</span>
                  <span className="text-slate-200 text-base">{sw?.xray_class ?? "—"}</span>
                </div>
                <div className="flex justify-between items-center pb-1">
                  <span className="text-slate-400">Covariance Inflation</span>
                  <span className="text-slate-200 text-base">
                    {lastSnap.covariance_inflation.toFixed(2)}×
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)]">
            <span>Object Metadata</span>
          </div>
          <div className="flex-1 p-5 flex flex-col gap-4 justify-center">
            <ObjectMetadataBlock
              isPrimary
              badgeColor={badgeColor}
              badgeText={badgeText}
              name={event.obj1.name}
              type={event.obj1.type}
              maneuverable={obj1Maneuverable}
              profile={obj1Profile}
            />
            <div className="border-t border-[rgba(255,255,255,0.06)]" />
            <ObjectMetadataBlock
              isPrimary={false}
              badgeColor={badgeColor}
              badgeText={badgeText}
              name={event.obj2.name}
              type={event.obj2.type}
              maneuverable={obj2Maneuverable}
              profile={obj2Profile}
            />
          </div>
        </div>
      </div>

      <div className="mt-auto border border-mission-border bg-mission-panel rounded-lg flex flex-col overflow-hidden">
        <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center">
          <span>Agent Reasoning Stream</span>
          <div className="flex items-center gap-2 bg-amber-500/10 px-2 py-0.5 rounded">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            <span className="text-amber-500 text-[10px] font-bold tracking-widest">PROCESSING</span>
          </div>
        </div>
        <AgentReasoningStream eventId={event.id} fallbackEvents={syntheticEvents} />
      </div>
    </div>
  );
}

// ── ObjectMetadataBlock ──────────────────────────────────────────────────

interface ObjectMetadataBlockProps {
  isPrimary: boolean;
  badgeColor: string;
  badgeText: string;
  name: string;
  type: string;
  maneuverable: boolean;
  profile: ReturnType<typeof syntheticAssetProfile>;
}

function ObjectMetadataBlock({
  isPrimary,
  badgeColor,
  badgeText,
  name,
  type,
  maneuverable,
  profile,
}: ObjectMetadataBlockProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        {isPrimary && (
          <span className={`px-2 py-0.5 rounded-full text-[9px] font-semibold tracking-wider ${badgeColor}`}>
            {badgeText}
          </span>
        )}
        <span className="font-bold text-slate-200 text-base">{name}</span>
        {maneuverable ? (
          <span className="ml-auto flex items-center gap-1 text-green-500 bg-green-500/10 px-2 py-0.5 rounded text-[10px] font-semibold">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
            MANEUVERABLE
          </span>
        ) : (
          <span className="ml-auto flex items-center gap-1 text-red-500 bg-red-500/10 px-2 py-0.5 rounded text-[10px] font-semibold">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
            </svg>
            NON-MANEUVERABLE
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] pl-1">
        <span className="text-slate-400">Type</span>
        <span className="text-slate-200 text-right">{type}</span>
        <span className="text-slate-400">Operator</span>
        <span className="text-slate-200 text-right">{profile.operator}</span>
        <span className="text-slate-400">Mass</span>
        <span className="text-slate-200 text-right">
          {profile.mass_kg.toLocaleString()} kg
        </span>
        <span className="text-slate-400">RCS</span>
        <span className="text-slate-200 text-right">{profile.rcs_m2.toFixed(2)} m²</span>
        {maneuverable && profile.delta_v_budget_mps > 0 && (
          <>
            <span className="text-slate-400">Fuel used</span>
            <span className="text-slate-200 text-right">
              {(profile.fuel_used_pct * 100).toFixed(0)}% ·{" "}
              <span className="text-cyan-400">
                {profile.delta_v_remaining_mps.toFixed(1)} m/s left
              </span>
            </span>
            <span className="text-slate-400">Criticality</span>
            <span className="text-amber-300 text-right uppercase">{profile.mission_criticality}</span>
          </>
        )}
      </div>
    </div>
  );
}
