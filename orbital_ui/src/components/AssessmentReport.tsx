import * as React from "react";
import type {
  AssetHistoryEntry,
  ManeuverPlanOption,
  ObjectProfile,
  VerdictEnriched,
} from "@/lib/types";

// ── Formatting helpers ────────────────────────────────────────────────────

function formatPc(pc: number | null | undefined): string {
  if (pc == null || !Number.isFinite(pc) || pc <= 0) return "—";
  const exp = Math.floor(Math.log10(pc));
  const mantissa = pc / Math.pow(10, exp);
  return `${mantissa.toFixed(2)} × 10${superscript(exp)}`;
}

const SUPER_DIGITS: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
  "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "-": "⁻", "+": "⁺",
};
function superscript(n: number): string {
  return String(n).split("").map((c) => SUPER_DIGITS[c] ?? c).join("");
}

function formatTimeToTca(tcaIso: string): string {
  const tca = new Date(tcaIso).getTime();
  const now = Date.now();
  const dt = tca - now;
  if (!Number.isFinite(dt)) return "—";
  const past = dt < 0;
  const abs = Math.abs(dt);
  const days = Math.floor(abs / 86_400_000);
  const hours = Math.floor((abs % 86_400_000) / 3_600_000);
  const mins = Math.floor((abs % 3_600_000) / 60_000);
  const prefix = past ? "T+" : "T-";
  if (days > 0) return `${prefix}${days}d ${hours}h ${mins}m`;
  return `${prefix}${hours}h ${mins}m`;
}

function formatMissDistance(km: number | undefined): string {
  if (km == null) return "—";
  if (km < 1) return `${(km * 1000).toFixed(0)} m`;
  return `${km.toFixed(3)} km`;
}

function pcBand(pc: number | undefined): { label: string; color: string } {
  if (pc == null || pc <= 0) return { label: "UNKNOWN", color: "text-slate-500 bg-slate-500/10" };
  if (pc < 1e-6) return { label: "NOISE", color: "text-slate-400 bg-slate-500/10" };
  if (pc < 1e-4) return { label: "WATCH", color: "text-amber-400 bg-amber-500/10" };
  return { label: "ACTION REQUIRED", color: "text-red-400 bg-red-500/10" };
}

function urgencyLabel(urgency: string | undefined): string {
  switch (urgency) {
    case "act_immediately": return "ACT IMMEDIATELY";
    case "act_within_6hr": return "Act within 6 hours";
    case "act_within_12hr": return "Act within 12 hours";
    case "act_within_24hr": return "Act within 24 hours";
    case "informational": return "Informational only";
    default: return "Urgency unspecified";
  }
}

function urgencyColor(urgency: string | undefined): string {
  switch (urgency) {
    case "act_immediately": return "text-red-400";
    case "act_within_6hr": return "text-red-300";
    case "act_within_12hr": return "text-amber-300";
    case "act_within_24hr": return "text-amber-200";
    default: return "text-slate-400";
  }
}

function burdenOfAvoidance(
  p1: ObjectProfile | undefined,
  p2: ObjectProfile | undefined,
): { label: string; color: string; explanation: string } {
  const m1 = p1?.is_maneuverable;
  const m2 = p2?.is_maneuverable;
  if (m1 === true && m2 === false) {
    return {
      label: "PRIMARY",
      color: "bg-amber-500/20 text-amber-400 border-amber-500/30",
      explanation: `${p2?.name ?? "Secondary"} is uncontrollable; ${p1?.name ?? "primary"} must maneuver.`,
    };
  }
  if (m1 === false && m2 === true) {
    return {
      label: "SECONDARY",
      color: "bg-amber-500/20 text-amber-400 border-amber-500/30",
      explanation: `${p1?.name ?? "Primary"} is uncontrollable; ${p2?.name ?? "secondary"} must maneuver.`,
    };
  }
  if (m1 === true && m2 === true) {
    return {
      label: "SHARED",
      color: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
      explanation: "Both objects are maneuverable; coordinate which one burns.",
    };
  }
  if (m1 === false && m2 === false) {
    return {
      label: "NEITHER",
      color: "bg-red-500/20 text-red-400 border-red-500/30",
      explanation: "Neither object is maneuverable — no avoidance possible from this side.",
    };
  }
  return {
    label: "UNKNOWN",
    color: "bg-slate-500/20 text-slate-400 border-slate-500/30",
    explanation: "Maneuverability not in catalog; assume primary asset operator decides.",
  };
}

// ── Sub-components ────────────────────────────────────────────────────────

function ObjectCard({
  role,
  profile,
  fallbackName,
  fallbackNoradId,
}: {
  role: "PRIMARY" | "SECONDARY";
  profile: ObjectProfile | undefined;
  fallbackName: string;
  fallbackNoradId: number;
}) {
  const p = profile;
  const maneuverable = p?.is_maneuverable;
  const maneuverableBadge = (() => {
    if (maneuverable === true)
      return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-500/20 text-green-400">MANEUVERABLE</span>;
    if (maneuverable === false)
      return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400">NON-MANEUVERABLE</span>;
    return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-500/20 text-slate-400">UNKNOWN</span>;
  })();

  return (
    <div className="border border-mission-border rounded-lg p-3 flex flex-col gap-2 bg-[#0a1018]">
      <div className="flex justify-between items-start gap-2">
        <div className="flex flex-col">
          <span className="text-[10px] uppercase text-slate-500 tracking-widest">{role}</span>
          <span className="text-slate-100 font-bold text-sm">{p?.name ?? fallbackName}</span>
          <span className="text-slate-500 text-[10px]">NORAD {p?.norad_id ?? fallbackNoradId}</span>
        </div>
        {maneuverableBadge}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <span className="text-slate-500">Operator</span>
        <span className="text-slate-300 text-right">{p?.operator ?? "—"}</span>
        <span className="text-slate-500">Country</span>
        <span className="text-slate-300 text-right">{p?.country ?? "—"}</span>
        <span className="text-slate-500">Type</span>
        <span className="text-slate-300 text-right">{p?.object_type ?? "—"}</span>
        {p?.fuel_remaining_mps != null && (
          <>
            <span className="text-slate-500">Fuel</span>
            <span className="text-green-400 text-right font-mono">{p.fuel_remaining_mps.toFixed(1)} m/s</span>
          </>
        )}
        {p?.mission_criticality && (
          <>
            <span className="text-slate-500">Criticality</span>
            <span className="text-amber-300 text-right uppercase">{p.mission_criticality}</span>
          </>
        )}
      </div>
    </div>
  );
}

function MetricRow({ label, value, valueClass }: { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div className="flex justify-between items-baseline border-b border-[rgba(255,255,255,0.05)] py-1">
      <span className="text-slate-500 text-[11px] uppercase tracking-wide">{label}</span>
      <span className={`text-slate-200 font-mono text-[12px] ${valueClass ?? ""}`}>{value}</span>
    </div>
  );
}

function HistoryRow({ entry, currentNorad }: { entry: AssetHistoryEntry; currentNorad: number }) {
  const partner =
    entry.obj1_name && entry.obj2_name && entry.obj1_name !== entry.obj2_name
      ? entry.obj1_name === `NORAD ${currentNorad}` ? entry.obj2_name : entry.obj1_name
      : entry.obj2_name;
  return (
    <div className="flex justify-between items-center text-[11px] py-1 border-b border-[rgba(255,255,255,0.04)]">
      <span className="text-slate-300 truncate max-w-[60%]">vs {partner}</span>
      <span className="text-slate-500 shrink-0">
        Pc {formatPc(entry.initial_pc)} · {entry.status}
      </span>
    </div>
  );
}

function PlanOptionCard({
  label,
  plan,
  recommended,
  onApprove,
  approving,
}: {
  label: string;
  plan: ManeuverPlanOption | undefined;
  recommended: boolean;
  onApprove: () => void;
  approving: boolean;
}) {
  const burns = plan?.burns_ms ?? [];
  const totalDv = plan?.total_delta_v_ms;
  return (
    <div
      className={`rounded-lg p-3 flex flex-col gap-2 ${
        recommended
          ? "border-2 border-[#378add] bg-[rgba(55,138,221,0.06)]"
          : "border border-mission-border bg-[#0a1018]"
      }`}
    >
      <div className="flex justify-between items-center gap-2">
        <span className={`font-bold text-sm ${recommended ? "text-[#378add]" : "text-slate-200"}`}>
          {plan?.label ?? label}
        </span>
        {recommended ? (
          <span className="px-1.5 py-0.5 bg-[#378add]/20 text-[#378add] text-[10px] font-bold uppercase rounded shrink-0">
            Recommended
          </span>
        ) : (
          <span className="text-slate-500 text-[10px] font-bold uppercase shrink-0">Alternative</span>
        )}
      </div>
      <div className="flex flex-col gap-1 text-[11px]">
        <MetricRow
          label="Burns"
          value={burns.length > 0 ? burns.map((b) => `${b.toFixed(2)} m/s`).join(" + ") : "—"}
        />
        <MetricRow
          label="Total Δv"
          value={totalDv != null ? `${totalDv.toFixed(3)} m/s` : "—"}
          valueClass="text-green-400 font-bold"
        />
        <MetricRow label="Events resolved" value={plan?.events_resolved ?? "—"} />
      </div>
      <button
        type="button"
        disabled={approving}
        onClick={onApprove}
        className={`mt-1 px-3 py-2 rounded font-bold text-xs ${
          recommended
            ? "bg-green-600 hover:bg-green-500 text-white disabled:opacity-50"
            : "border border-mission-border bg-mission-panel hover:bg-white/5 text-slate-200 disabled:opacity-50"
        }`}
      >
        {approving ? "Approving…" : `Approve ${plan?.label ?? label}`}
      </button>
    </div>
  );
}

// ── Main report ───────────────────────────────────────────────────────────

export interface AssessmentReportProps {
  verdict: VerdictEnriched;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
}

export function AssessmentReport({ verdict: v, onApprove, onReject, approving }: AssessmentReportProps) {
  const plan = v.plan;
  const planEntries = plan?.plans ? Object.entries(plan.plans) : [];
  const recommendedKey = plan?.recommended;
  const band = pcBand(v.current_pc);
  const burden = burdenOfAvoidance(v.obj1_profile, v.obj2_profile);
  const tcaText = v.event?.tca ? formatTimeToTca(v.event.tca) : "—";

  return (
    <div className="rounded-lg border border-red-500/20 bg-[#0a1018] flex flex-col font-mono text-slate-200 shadow-[0_0_20px_rgba(239,68,68,0.04)]">
      {/* Header */}
      <div className="border-b border-mission-border px-5 py-3 flex justify-between items-start gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-slate-500 uppercase tracking-widest">
            Orbital Conjunction Assessment
          </span>
          <span className="text-slate-100 font-bold text-base">
            {v.event?.obj1_name ?? "?"} ↔ {v.event?.obj2_name ?? "?"}
          </span>
          <span className="text-slate-500 text-[10px]">Event {v.event_id}</span>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider ${band.color}`}
          >
            {band.label}
          </span>
          <span className="text-amber-300 font-bold text-base">{tcaText}</span>
          <span className="text-slate-500 text-[10px]">until TCA</span>
        </div>
      </div>

      {/* Urgency */}
      {plan?.urgency && (
        <div className={`px-5 py-2 border-b border-mission-border ${urgencyColor(plan.urgency)} text-xs`}>
          <span className="text-slate-500 uppercase tracking-wider mr-2">Urgency:</span>
          <span className="font-bold uppercase">{urgencyLabel(plan.urgency)}</span>
        </div>
      )}

      {/* Objects */}
      <div className="px-5 py-3 border-b border-mission-border">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-slate-500 uppercase tracking-widest">Objects involved</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${burden.color}`}>
            BURDEN: {burden.label}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <ObjectCard
            role="PRIMARY"
            profile={v.obj1_profile}
            fallbackName={v.event?.obj1_name ?? "Primary"}
            fallbackNoradId={v.event?.obj1_norad_id ?? 0}
          />
          <ObjectCard
            role="SECONDARY"
            profile={v.obj2_profile}
            fallbackName={v.event?.obj2_name ?? "Secondary"}
            fallbackNoradId={v.event?.obj2_norad_id ?? 0}
          />
        </div>
        <p className="text-[10px] text-slate-500 mt-2 italic">{burden.explanation}</p>
      </div>

      {/* Encounter Geometry + Risk */}
      <div className="px-5 py-3 border-b border-mission-border grid grid-cols-2 gap-x-6 gap-y-1">
        <div className="col-span-2 text-[10px] text-slate-500 uppercase tracking-widest mb-1">
          Encounter geometry &amp; risk
        </div>
        <MetricRow label="TCA (UTC)" value={v.event?.tca?.slice(0, 19).replace("T", " ") ?? "—"} />
        <MetricRow label="Pc band" value={band.label} valueClass={band.color.replace("bg-", "").split(" ").find((c) => c.startsWith("text-")) ?? ""} />
        <MetricRow label="Miss distance" value={formatMissDistance(v.current_miss_km)} />
        <MetricRow label="Relative velocity" value={v.event?.relative_velocity_km_s != null ? `${v.event.relative_velocity_km_s.toFixed(2)} km/s` : "—"} />
        <MetricRow label="Initial Pc" value={formatPc(v.event?.initial_pc)} />
        <MetricRow label="Refined Pc" value={formatPc(v.current_pc)} valueClass="text-amber-300 font-bold" />
        {v.refinement && (
          <>
            <MetricRow
              label="Covariance σ ×"
              value={v.refinement.covariance_inflation.toFixed(2)}
              valueClass={v.refinement.covariance_inflation > 1 ? "text-amber-300" : ""}
            />
            <MetricRow
              label="Kp at refinement"
              value={v.refinement.kp_index != null ? v.refinement.kp_index.toFixed(2) : "—"}
            />
          </>
        )}
      </div>

      {/* Space weather */}
      {v.space_weather && (
        <div className="px-5 py-3 border-b border-mission-border">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Space weather</div>
          <div className="grid grid-cols-3 gap-x-4">
            <MetricRow label="Kp" value={v.space_weather.kp_index.toFixed(2)} />
            <MetricRow label="Storm level" value={v.space_weather.geomag_storm_level} />
            <MetricRow label="X-ray" value={`${v.space_weather.xray_class}`} />
          </div>
        </div>
      )}

      {/* Decision context (asset history) */}
      {v.asset_history && v.asset_history.length > 0 && (
        <div className="px-5 py-3 border-b border-mission-border">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
            Decision context — prior events for {v.obj1_profile?.name ?? "primary asset"}
          </div>
          <div className="flex flex-col">
            {v.asset_history.map((h) => (
              <HistoryRow key={h.event_id} entry={h} currentNorad={v.event?.obj1_norad_id ?? 0} />
            ))}
          </div>
        </div>
      )}

      {/* Recommendation */}
      <div className="px-5 py-3 border-b border-mission-border">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-2">Recommendation</div>
        {planEntries.length === 0 ? (
          <p className="text-slate-500 text-xs italic">No structured plan attached.</p>
        ) : (
          <div className={`grid gap-3 ${planEntries.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
            {planEntries.map(([key, opt]) => (
              <PlanOptionCard
                key={key}
                label={key}
                plan={opt}
                recommended={key === recommendedKey}
                approving={approving}
                onApprove={onApprove}
              />
            ))}
          </div>
        )}
      </div>

      {/* Reasoning */}
      <div className="px-5 py-3 border-b border-mission-border">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Reasoning</div>
        <p className="text-[#c8d6e8] text-xs leading-relaxed whitespace-pre-wrap">
          {v.reasoning || "(no reasoning attached)"}
        </p>
      </div>

      {/* Footer actions */}
      <div className="px-5 py-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onReject}
          className="px-4 py-2 border border-mission-border bg-mission-panel hover:bg-white/5 text-slate-300 rounded text-xs font-bold"
        >
          Reject — Do Nothing
        </button>
        <span className="text-[10px] text-slate-600 italic">
          Generated by Orbital v0.1 · {v.issued_at.slice(0, 19).replace("T", " ")}
        </span>
      </div>
    </div>
  );
}
