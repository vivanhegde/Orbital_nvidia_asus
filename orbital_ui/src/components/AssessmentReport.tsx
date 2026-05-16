import * as React from "react";
import type { VerdictEnriched, ObjectProfile, AssetHistoryEntry } from "@/lib/types";

interface AssessmentReportProps {
  verdict: VerdictEnriched;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
}

function formatPc(pc: number): string {
  if (pc === 0) return "0";
  const exp = Math.floor(Math.log10(Math.abs(pc)));
  const mantissa = pc / Math.pow(10, exp);
  return `${mantissa.toFixed(1)} × 10⁻${Math.abs(exp)}`;
}

function formatTimeToTca(tcaIso: string): string {
  const tca = new Date(tcaIso);
  const now = new Date();
  const diffMs = tca.getTime() - now.getTime();
  if (diffMs <= 0) return "PASSED";
  const hours = Math.floor(diffMs / 3_600_000);
  const mins = Math.floor((diffMs % 3_600_000) / 60_000);
  return `T-${hours}h ${mins}m`;
}

function urgencyFromPlan(plan: VerdictEnriched["plan"]): string {
  const raw = plan?.urgency;
  if (raw) return raw.replace(/_/g, " ").toUpperCase();
  return "ACT WITHIN 24 HOURS";
}

function ObjectSection({ profile, role }: { profile: ObjectProfile | undefined; role: "Primary" | "Secondary" }) {
  if (!profile) return null;
  const kind = (profile.object_type || "").toUpperCase();
  const isDebris = kind.includes("DEB");
  const isRB = kind.includes("R/B");
  const typeLabel = isDebris ? "Debris fragment" : isRB ? "Rocket body" : "Active payload";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{role}</span>
        {profile.is_maneuverable === true && (
          <span className="px-1.5 py-0.5 bg-green-500/10 text-green-400 text-[9px] font-bold rounded">MANEUVERABLE</span>
        )}
        {profile.is_maneuverable === false && (
          <span className="px-1.5 py-0.5 bg-slate-500/10 text-slate-500 text-[9px] font-bold rounded">NON-MANEUVERABLE</span>
        )}
      </div>
      <span className="text-sm font-bold text-slate-100">
        {profile.name ?? `NORAD ${profile.norad_id}`}
        <span className="text-slate-500 font-normal ml-2">(NORAD {profile.norad_id})</span>
      </span>
      <div className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-0.5">
        {profile.operator && <span>{profile.operator}</span>}
        <span>{typeLabel}</span>
        {profile.country && <span>{profile.country}</span>}
      </div>
      {profile.is_maneuverable && (
        <div className="text-xs text-slate-400 flex gap-x-4">
          {profile.fuel_remaining_mps != null && (
            <span>Δv budget: <span className="text-slate-200">{profile.fuel_remaining_mps.toFixed(1)} m/s</span></span>
          )}
          {profile.mission_criticality && (
            <span>Criticality: <span className="text-slate-200 capitalize">{profile.mission_criticality}</span></span>
          )}
        </div>
      )}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mt-5 mb-2">
      <div className="h-px flex-1 bg-[rgba(255,255,255,0.06)]" />
      <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-slate-500">{children}</span>
      <div className="h-px flex-1 bg-[rgba(255,255,255,0.06)]" />
    </div>
  );
}

function DataRow({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div className="flex justify-between items-baseline py-1 border-b border-[rgba(255,255,255,0.04)] last:border-b-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-medium ${accent ?? "text-slate-200"}`}>{value}</span>
    </div>
  );
}

function PlanSection({
  plan,
  isRecommended,
  onApprove,
  approving,
}: {
  plan: { label: string; burns_ms?: number[]; total_delta_v_ms?: number; events_resolved?: number };
  isRecommended: boolean;
  onApprove: () => void;
  approving: boolean;
}) {
  return (
    <div className={`rounded-lg p-4 flex flex-col gap-2 border ${
      isRecommended
        ? "border-[#378add] bg-[rgba(55,138,221,0.04)]"
        : "border-mission-border bg-[rgba(255,255,255,0.02)]"
    }`}>
      <div className="flex justify-between items-center mb-1">
        <span className={`font-bold text-sm ${isRecommended ? "text-[#378add]" : "text-slate-300"}`}>
          {plan.label}
        </span>
        {isRecommended && (
          <span className="px-2 py-0.5 bg-[#378add]/20 text-[#378add] text-[9px] font-bold uppercase rounded tracking-wider">
            Recommended
          </span>
        )}
      </div>
      <div className="flex flex-col gap-0.5">
        <DataRow
          label="Total Δv"
          value={plan.total_delta_v_ms != null ? `${plan.total_delta_v_ms.toFixed(2)} m/s` : "—"}
          accent="text-green-400"
        />
        <DataRow
          label="Burns"
          value={plan.burns_ms?.length ? plan.burns_ms.map(b => `${b.toFixed(2)} m/s`).join(" → ") : "—"}
        />
        <DataRow
          label="Events resolved"
          value={plan.events_resolved ?? "—"}
        />
      </div>
      <button
        type="button"
        disabled={approving}
        onClick={onApprove}
        className={`mt-2 px-4 py-2 rounded font-bold text-xs transition-colors ${
          isRecommended
            ? "bg-green-600 hover:bg-green-500 text-white disabled:opacity-50"
            : "border border-mission-border bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.06)] text-slate-300 disabled:opacity-50"
        }`}
      >
        Approve {plan.label}
      </button>
    </div>
  );
}

export function AssessmentReport({ verdict, onApprove, onReject, approving }: AssessmentReportProps) {
  const ev = verdict.event;
  const plan = verdict.plan;
  const sw = verdict.space_weather;
  const ref = verdict.refinement;
  const history = verdict.asset_history ?? [];

  const pcBand = verdict.current_pc != null && verdict.current_pc >= 1e-4
    ? "ACTION REQUIRED"
    : verdict.current_pc != null && verdict.current_pc >= 1e-6
      ? "WATCH"
      : "NOISE";

  const burden = verdict.obj1_profile?.is_maneuverable === true && verdict.obj2_profile?.is_maneuverable === false
    ? "PRIMARY"
    : verdict.obj1_profile?.is_maneuverable === false && verdict.obj2_profile?.is_maneuverable === true
      ? "SECONDARY"
      : "SHARED";

  return (
    <div className="bg-[#0a1018] border border-red-500/20 rounded-xl p-6 flex flex-col gap-0 shadow-[0_0_30px_rgba(239,68,68,0.04)] font-mono">
      {/* Header */}
      <div className="flex justify-between items-start mb-1">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
            Orbital Conjunction Assessment
          </span>
          <div className="text-xs text-slate-500 mt-0.5">Event ID: {verdict.event_id}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider bg-red-500/20 text-red-400">
            {verdict.verdict_type.toUpperCase()}
          </span>
          {ev?.tca && (
            <span className="text-[10px] text-amber-400 font-bold">{formatTimeToTca(ev.tca)}</span>
          )}
        </div>
      </div>

      <div className="text-xs font-bold text-amber-400 mt-1 mb-3">
        {urgencyFromPlan(plan as VerdictEnriched["plan"])}
      </div>

      {/* Objects */}
      <SectionHeader>Objects</SectionHeader>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ObjectSection profile={verdict.obj1_profile} role="Primary" />
        <ObjectSection profile={verdict.obj2_profile} role="Secondary" />
      </div>
      {burden !== "SHARED" && (
        <div className="text-[10px] text-slate-500 mt-2">
          Burden of avoidance: <span className="text-slate-300 font-bold">{burden}</span>
        </div>
      )}

      {/* Encounter Geometry */}
      <SectionHeader>Encounter Geometry</SectionHeader>
      <div className="grid grid-cols-2 gap-x-6">
        <DataRow label="TCA (UTC)" value={ev?.tca ? new Date(ev.tca).toUTCString().replace("GMT", "UTC") : "—"} />
        <DataRow
          label="Miss distance"
          value={ev?.miss_distance_km != null ? `${(ev.miss_distance_km * 1000).toFixed(0)} m` : verdict.current_miss_km != null ? `${(verdict.current_miss_km * 1000).toFixed(0)} m` : "—"}
        />
        <DataRow
          label="Relative velocity"
          value={ev?.relative_velocity_km_s != null ? `${ev.relative_velocity_km_s.toFixed(1)} km/s` : "—"}
          accent="text-red-400"
        />
        <DataRow label="Status" value={pcBand} accent={pcBand === "ACTION REQUIRED" ? "text-red-400" : "text-amber-400"} />
      </div>

      {/* Risk Assessment */}
      <SectionHeader>Risk Assessment</SectionHeader>
      <div className="grid grid-cols-2 gap-x-6">
        <DataRow
          label="Initial Pc (screening)"
          value={ev?.initial_pc != null ? formatPc(ev.initial_pc) : "—"}
        />
        <DataRow
          label="Refined Pc"
          value={verdict.current_pc != null ? formatPc(verdict.current_pc) : "—"}
          accent={verdict.current_pc != null && verdict.current_pc >= 1e-4 ? "text-red-400" : "text-amber-400"}
        />
        {ref?.covariance_inflation != null && ref.covariance_inflation > 1.0 && (
          <DataRow
            label="Covariance inflation"
            value={`${ref.covariance_inflation.toFixed(2)}×`}
            accent="text-amber-400"
          />
        )}
        {ref?.kp_index != null && (
          <DataRow
            label="Kp index"
            value={ref.kp_index.toFixed(1)}
            accent={ref.kp_index >= 5 ? "text-amber-400" : "text-slate-200"}
          />
        )}
      </div>

      {/* Space Weather */}
      {sw && (
        <>
          <SectionHeader>Space Weather</SectionHeader>
          <div className="grid grid-cols-2 gap-x-6">
            <DataRow label="Kp index" value={sw.kp_index?.toFixed(1) ?? "—"} accent={sw.kp_index >= 5 ? "text-amber-400" : "text-slate-200"} />
            <DataRow label="Storm level" value={sw.geomag_storm_level ?? "Quiet"} />
            <DataRow label="X-ray class" value={sw.xray_class ?? "—"} />
          </div>
        </>
      )}

      {/* Decision Context */}
      {history.length > 0 && (
        <>
          <SectionHeader>Decision Context</SectionHeader>
          <div className="text-xs text-slate-400 mb-1">
            Recent history for {verdict.obj1_profile?.name ?? `NORAD ${ev?.obj1_norad_id}`} (last 30 days):
          </div>
          <div className="flex flex-col gap-1">
            {history.map((h: AssetHistoryEntry) => (
              <div key={h.event_id} className="flex justify-between text-xs border-b border-[rgba(255,255,255,0.03)] py-0.5">
                <span className="text-slate-400">{h.obj2_name}</span>
                <span className="text-slate-500">
                  Pc {formatPc(h.initial_pc)} · <span className="capitalize">{h.status}</span>
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Recommendation / Plans */}
      {plan && Object.keys(plan.plans ?? {}).length > 0 && (
        <>
          <SectionHeader>Recommendation</SectionHeader>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(plan.plans).map(([key, p]) => (
              <PlanSection
                key={key}
                plan={p}
                isRecommended={plan.recommended === key}
                onApprove={onApprove}
                approving={approving}
              />
            ))}
          </div>
        </>
      )}

      {/* Reasoning */}
      <SectionHeader>Reasoning</SectionHeader>
      <p className="text-xs text-[#c8d6e8] leading-relaxed whitespace-pre-wrap">{verdict.reasoning}</p>

      {/* Actions */}
      <div className="flex gap-3 mt-5 pt-4 border-t border-[rgba(255,255,255,0.06)]">
        <button
          type="button"
          disabled={approving}
          onClick={onReject}
          className="px-4 py-2 border border-mission-border bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.06)] text-slate-300 rounded text-xs font-bold transition-colors disabled:opacity-40"
        >
          Reject — Do Nothing
        </button>
      </div>

      {/* Footer */}
      <div className="text-[10px] text-slate-600 mt-4 pt-3 border-t border-[rgba(255,255,255,0.04)] flex justify-between">
        <span>Generated by Orbital v0.1 · {new Date(verdict.issued_at).toUTCString().replace("GMT", "UTC")}</span>
        <span>On-device inference via OpenClaw on ASUS Ascent GX10</span>
      </div>
    </div>
  );
}
