import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  approveVerdict,
  getPendingVerdicts,
  rejectVerdict,
  synthesizeDemoVerdict,
} from "@/lib/api";
import type { ManeuverPlanOption, SyntheticPlanPayload, VerdictEnriched } from "@/lib/types";

export interface ApproverViewProps {
  onNavigate: (view: "dashboard" | "approver" | "memory") => void;
}

function formatBurns(plan: ManeuverPlanOption | undefined): string {
  const b = plan?.burns_ms;
  if (!b?.length) return "—";
  return b.map((x) => `${x.toFixed(2)} m/s`).join(", ");
}

function PlanCard({
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
  const dv =
    plan?.total_delta_v_ms != null ? `${plan.total_delta_v_ms.toFixed(2)} m/s` : "—";
  return (
    <div
      className={`rounded-lg p-4 flex flex-col gap-3 border ${
        recommended
          ? "border-2 border-[#378add] bg-[rgba(55,138,221,0.05)]"
          : "border border-mission-border bg-mission-panel"
      }`}
    >
      <div className="flex justify-between items-center">
        <span className={`font-bold ${recommended ? "text-[#378add]" : "text-slate-200"}`}>{label}</span>
        {recommended ? (
          <span className="px-2 py-0.5 bg-[#378add]/20 text-[#378add] text-[10px] font-bold uppercase rounded">
            Recommended
          </span>
        ) : (
          <span className="text-slate-500 text-[10px] font-bold uppercase">Alternative</span>
        )}
      </div>
      <div className="flex flex-col gap-1 text-xs">
        <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] pb-1">
          <span className="text-slate-400">Burn sequence</span>
          <span className="text-slate-200 text-right max-w-[60%]">{formatBurns(plan)}</span>
        </div>
        <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] py-1">
          <span className="text-slate-400">Total Δv</span>
          <span className="text-green-500 font-bold">{dv}</span>
        </div>
        <div className="flex justify-between pt-1">
          <span className="text-slate-400">Events resolved</span>
          <span className="text-slate-200">{plan?.events_resolved ?? "—"}</span>
        </div>
      </div>
      <button
        type="button"
        disabled={approving}
        onClick={onApprove}
        className={`mt-1 px-3 py-2 rounded font-bold text-sm ${
          recommended
            ? "bg-green-600 hover:bg-green-500 text-white disabled:opacity-50"
            : "border border-mission-border bg-mission-panel hover:bg-white/5 disabled:opacity-50"
        }`}
      >
        Approve {label}
      </button>
    </div>
  );
}

export function ApproverView({ onNavigate }: ApproverViewProps) {
  const queryClient = useQueryClient();
  const [demoEventId, setDemoEventId] = React.useState("");

  const pendingQuery = useQuery({
    queryKey: ["verdicts-pending"],
    queryFn: getPendingVerdicts,
    refetchInterval: 10_000,
  });

  const approveMut = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) => approveVerdict(id, notes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["verdicts-pending"] });
      toast.success("Decision recorded.");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Approve failed"),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) => rejectVerdict(id, notes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["verdicts-pending"] });
      toast.success("Rejected.");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Reject failed"),
  });

  const synthMut = useMutation({
    mutationFn: (eventId: string) => synthesizeDemoVerdict(eventId.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["verdicts-pending"] });
      toast.success("Synthetic verdict inserted.");
      setDemoEventId("");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Synthesize failed"),
  });

  const verdicts = pendingQuery.data?.verdicts ?? [];

  return (
    <div className="flex flex-col min-h-screen bg-[#060b14] text-slate-200 font-mono text-sm p-4 gap-[10px]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="font-bold tracking-widest text-slate-100">ORBITAL</span>
        </div>
        <div className="flex gap-6 text-slate-400">
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("dashboard")}>
            Dashboard
          </span>
          <span className="text-white cursor-pointer">Approver</span>
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("memory")}>
            Memory
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-500 text-xs font-semibold tracking-wider">
            PLANNING
          </span>
        </div>
      </div>

      {pendingQuery.isLoading ? (
        <p className="text-slate-500">Loading pending verdicts…</p>
      ) : pendingQuery.isError ? (
        <p className="text-red-400 text-sm">Could not load verdicts.</p>
      ) : verdicts.length === 0 ? (
        <div className="bg-mission-panel border border-mission-border rounded-lg p-6 text-slate-500 text-sm">
          <p>No pending maneuver recommendations. Paste an event_id from Memory into the demo box below,</p>
          <p className="mt-2">or POST</p>
          <code className="text-[11px] text-slate-400 block mt-1">/api/dev/synthesize-verdict</code>
        </div>
      ) : null}

      {verdicts.map((v: VerdictEnriched) => {
        const plan = v.plan as SyntheticPlanPayload | null;
        const rec = plan?.recommended ?? "B";
        const planB = plan?.plans?.B;
        const planA = plan?.plans?.A;
        return (
          <div
            key={v.verdict_id}
            className="bg-mission-panel border border-red-500/30 rounded-lg p-5 flex flex-col gap-4 shadow-[0_0_15px_rgba(239,68,68,0.05)]"
          >
            <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-3">
              <div>
                <span className="font-bold text-lg text-slate-100 block">
                  {v.event?.obj1_name ?? "?"} ↔ {v.event?.obj2_name ?? "?"}
                </span>
                <span className="text-slate-500 text-xs">
                  TCA {v.event?.tca ?? "—"} · current Pc {(v.current_pc ?? 0).toExponential(2)}
                  {v.current_miss_km != null ? ` · miss ${v.current_miss_km.toFixed(2)} km` : ""}
                </span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider bg-red-500/20 text-red-500">
                {v.verdict_type.toUpperCase()}
              </span>
            </div>

            <p className="text-[#c8d6e8] leading-relaxed text-sm">{v.reasoning}</p>

            <div className="grid grid-cols-2 gap-4 mt-2">
              <PlanCard
                label={planB?.label ?? "Plan B"}
                plan={planB}
                recommended={rec === "B"}
                approving={approveMut.isPending}
                onApprove={() => approveMut.mutate({ id: v.verdict_id })}
              />
              <PlanCard
                label={planA?.label ?? "Plan A"}
                plan={planA}
                recommended={rec === "A"}
                approving={approveMut.isPending}
                onApprove={() => approveMut.mutate({ id: v.verdict_id })}
              />
            </div>

            <div className="flex gap-3 mt-2 flex-wrap">
              <button
                type="button"
                onClick={() => rejectMut.mutate({ id: v.verdict_id })}
                className="px-4 py-2 border border-mission-border bg-mission-panel hover:bg-white/5 text-slate-200 rounded"
              >
                Reject — do nothing
              </button>
            </div>
          </div>
        );
      })}

      <div className="bg-mission-panel border border-dashed border-slate-600 rounded-lg p-4 mt-4">
        <p className="text-[11px] text-slate-500 uppercase tracking-wide mb-2">Demo — synthetic verdict</p>
        <div className="flex gap-2 flex-wrap items-center">
          <input
            value={demoEventId}
            onChange={(e) => setDemoEventId(e.target.value)}
            placeholder="Paste event_id from Memory tab"
            className="flex-1 min-w-[200px] bg-[#060b14] border border-mission-border rounded px-3 py-2 text-slate-200 text-xs"
          />
          <button
            type="button"
            disabled={!demoEventId.trim() || synthMut.isPending}
            onClick={() => synthMut.mutate(demoEventId)}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-xs font-bold disabled:opacity-40"
          >
            Generate
          </button>
        </div>
      </div>
    </div>
  );
}
