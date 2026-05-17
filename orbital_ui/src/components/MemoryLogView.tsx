import { useQuery } from "@tanstack/react-query";
import { getDecidedVerdicts, getMemoryRecent } from "@/lib/api";
import type { MemoryEventRow, VerdictEnriched } from "@/lib/types";
import { formatRelativeFromNow, formatUtcAbsolute } from "@/lib/time";

export interface MemoryLogViewProps {
  onNavigate: (view: "dashboard" | "approver" | "memory") => void;
  onSelectEvent: (eventId: string) => void;
}

export function MemoryLogView({ onNavigate, onSelectEvent }: MemoryLogViewProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["memory-recent"],
    queryFn: () => getMemoryRecent(50),
    refetchInterval: 60_000,
  });

  const decidedQuery = useQuery({
    queryKey: ["verdicts-decided"],
    queryFn: () => getDecidedVerdicts(50),
    refetchInterval: 30_000,
  });

  const events: MemoryEventRow[] = data?.events ?? [];
  const decided: VerdictEnriched[] = decidedQuery.data?.verdicts ?? [];

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
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("approver")}>
            Approver
          </span>
          <span className="text-white cursor-pointer">Memory</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-xs">SQLite · orbital_data/orbital.db</span>
        </div>
      </div>

      <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
        <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)] flex justify-between items-center">
          <span>Operator decisions</span>
          <span className="text-slate-500 text-[10px]">approved + rejected verdicts, newest first</span>
        </div>
        <div className="p-[14px]">
          {decidedQuery.isLoading ? (
            <p className="text-slate-500 text-xs">Loading decisions…</p>
          ) : decided.length === 0 ? (
            <p className="text-slate-500 text-xs">
              No decisions yet. Approve or reject a recommended verdict on the Approver tab and it'll log here.
            </p>
          ) : (
            <div className="flex flex-col border border-mission-border bg-[#060b14] rounded overflow-hidden">
              <div className="flex px-4 py-2 bg-[#060b14] text-[#3a5060] text-[10px] uppercase border-b border-[rgba(255,255,255,0.06)]">
                <div className="w-[16%]">Decided</div>
                <div className="w-[14%]">Decision</div>
                <div className="w-[28%]">Pair</div>
                <div className="w-[12%]">Total Δv</div>
                <div className="w-[14%]">Issued</div>
                <div className="w-[16%]">Notes</div>
              </div>
              {decided.map((v) => {
                const isApproved = v.operator_decision === "approved";
                const planEntries = v.plan?.plans ? Object.entries(v.plan.plans) : [];
                const recKey = v.plan?.recommended;
                const primary = recKey
                  ? v.plan?.plans[recKey]
                  : planEntries[0]?.[1];
                const dv = primary?.total_delta_v_ms;
                return (
                  <button
                    key={v.verdict_id}
                    type="button"
                    onClick={() => {
                      onSelectEvent(v.event_id);
                      onNavigate("dashboard");
                    }}
                    className="flex items-center w-full text-left gap-2 px-4 py-3 border-b border-[rgba(255,255,255,0.06)] hover:bg-white/5 transition-colors text-xs"
                  >
                    <div className="w-[16%] text-slate-400 leading-tight">
                      <div>{v.operator_decided_at ? formatRelativeFromNow(v.operator_decided_at) : "—"}</div>
                      <div className="text-[10px] text-slate-600">
                        {v.operator_decided_at ? formatUtcAbsolute(v.operator_decided_at).slice(11, 19) : ""}
                      </div>
                    </div>
                    <div className="w-[14%]">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider ${
                          isApproved
                            ? "bg-green-500/20 text-green-400"
                            : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {isApproved ? "APPROVED" : "REJECTED"}
                      </span>
                    </div>
                    <div className="w-[28%] truncate text-slate-200">
                      {v.event?.obj1_name ?? "?"} ↔ {v.event?.obj2_name ?? "?"}
                    </div>
                    <div className="w-[12%] text-cyan-300">
                      {dv != null ? `${dv.toFixed(2)} m/s` : "—"}
                    </div>
                    <div className="w-[14%] text-[#3a5060] text-[10px]">
                      {formatUtcAbsolute(v.issued_at).slice(11, 19)}
                    </div>
                    <div className="w-[16%] truncate text-slate-500 text-[10px] italic" title={v.operator_notes ?? ""}>
                      {v.operator_notes ?? "—"}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
        <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)]">
          <span>Conjunction event log</span>
        </div>

        <div className="p-[14px] flex flex-col gap-[14px]">
          {isLoading ? (
            <p className="text-slate-500 text-sm">Loading events…</p>
          ) : isError ? (
            <p className="text-red-400 text-sm">{error instanceof Error ? error.message : "Failed to load"}</p>
          ) : events.length === 0 ? (
            <p className="text-slate-500 text-sm">
              No persisted events yet. Ensure the API is running so the screener can write to SQLite.
            </p>
          ) : (
            <div className="flex flex-col border border-mission-border bg-[#060b14] rounded overflow-hidden">
              <div className="flex px-4 py-2 bg-[#060b14] text-[#3a5060] text-[10px] uppercase border-b border-[rgba(255,255,255,0.06)]">
                <div className="w-[14%]">Event</div>
                <div className="w-[26%]">Pair</div>
                <div className="w-[18%]">TCA</div>
                <div className="w-[12%]">Initial Pc</div>
                <div className="w-[12%]">Status</div>
                <div className="w-[18%]">Last seen</div>
              </div>
              {events.map((r) => (
                <button
                  key={r.event_id}
                  type="button"
                  onClick={() => {
                    onSelectEvent(r.event_id);
                    onNavigate("dashboard");
                  }}
                  className="flex items-center w-full text-left gap-2 px-4 py-3 border-b border-[rgba(255,255,255,0.06)] hover:bg-white/5 transition-colors text-xs"
                >
                  <div className="w-[14%] truncate text-[#7a9ab0] font-mono" title={r.event_id}>
                    {r.event_id.slice(0, 8)}…
                  </div>
                  <div className="w-[26%] truncate text-slate-200">
                    {r.obj1_name} ↔ {r.obj2_name}
                  </div>
                  <div className="w-[18%] text-slate-400 leading-tight">
                    <div>{formatRelativeFromNow(r.tca)}</div>
                    <div className="text-[10px] text-slate-600">{formatUtcAbsolute(r.tca).slice(0, 19)}</div>
                  </div>
                  <div className="w-[12%] text-cyan-300">{r.initial_pc.toExponential(1)}</div>
                  <div className="w-[12%] uppercase text-[10px] text-amber-200/90">{r.status}</div>
                  <div className="w-[18%] text-[#3a5060] text-[10px]">
                    {formatUtcAbsolute(r.last_seen_at).slice(0, 19)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
