import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  approveVerdict,
  getPendingVerdicts,
  rejectVerdict,
  synthesizeDemoVerdict,
} from "@/lib/api";
import type { VerdictEnriched } from "@/lib/types";
import { AssessmentReport } from "./AssessmentReport";

export interface ApproverViewProps {
  onNavigate: (view: "dashboard" | "approver" | "memory") => void;
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
    <div className="flex flex-col min-h-screen bg-[#060b14] text-slate-200 font-mono text-sm p-4 gap-3">
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
          <p>No pending maneuver recommendations.</p>
          <p className="mt-2 text-xs">
            Recommendations only appear here when the agent escalates an event to Plan mode
            (refined Pc ≥ 1e-4). Use the demo synthesizer below to inject one for testing.
          </p>
        </div>
      ) : null}

      {verdicts.map((v: VerdictEnriched) => (
        <AssessmentReport
          key={v.verdict_id}
          verdict={v}
          onApprove={() => approveMut.mutate({ id: v.verdict_id })}
          onReject={() => rejectMut.mutate({ id: v.verdict_id })}
          approving={approveMut.isPending && approveMut.variables?.id === v.verdict_id}
        />
      ))}

      <div className="bg-mission-panel border border-dashed border-slate-600 rounded-lg p-4 mt-4">
        <p className="text-[11px] text-slate-500 uppercase tracking-wide mb-2">Demo — synthetic verdict</p>
        <p className="text-[10px] text-slate-600 mb-3">
          Paste an event_id from the Memory tab and click Generate to inject a hardcoded
          two-plan recommendation. Useful for showing the full assessment report without
          waiting for the agent.
        </p>
        <div className="flex gap-2 flex-wrap items-center">
          <input
            value={demoEventId}
            onChange={(e) => setDemoEventId(e.target.value)}
            placeholder="event_id (40-char SHA hex)"
            className="flex-1 min-w-[260px] bg-[#060b14] border border-mission-border rounded px-3 py-2 text-slate-200 text-xs font-mono"
          />
          <button
            type="button"
            disabled={!demoEventId.trim() || synthMut.isPending}
            onClick={() => synthMut.mutate(demoEventId)}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-xs font-bold disabled:opacity-40"
          >
            {synthMut.isPending ? "Generating…" : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
