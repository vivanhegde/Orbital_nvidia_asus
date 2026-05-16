import { toast } from "sonner";

export interface ApproverViewProps {
  onNavigate: (view: "dashboard" | "approver" | "memory") => void;
}

export function ApproverView({ onNavigate }: ApproverViewProps) {
  const handleApprove = (plan: string) => {
    toast(`Plan ${plan} approved. Writing to memory and resolving conjunctions...`);
    onNavigate("dashboard");
  };

  return (
    <div className="flex flex-col min-h-screen bg-[#060b14] text-slate-200 font-mono text-sm p-4 gap-[10px]">
      
      {/* NavBar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="font-bold tracking-widest text-slate-100">ORBITAL</span>
        </div>
        <div className="flex gap-6 text-slate-400">
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("dashboard")}>Dashboard</span>
          <span className="text-white cursor-pointer">Approver</span>
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("memory")}>Memory</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-500 text-xs font-semibold tracking-wider">PLANNING</span>
        </div>
      </div>

      <div className="flex flex-col gap-[10px]">
        {/* Recommendation Card */}
        <div className="bg-mission-panel border border-red-500/30 rounded-lg p-5 flex flex-col gap-4 shadow-[0_0_15px_rgba(239,68,68,0.05)]">
          <div className="flex justify-between items-center border-b border-[rgba(255,255,255,0.06)] pb-3">
            <div className="flex items-center gap-3">
              <span className="font-bold text-lg text-slate-100">SL-4521</span>
              <span className="text-slate-400">Maneuver recommendation</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider bg-red-500/20 text-red-500">URGENT</span>
          </div>
          
          <p className="text-[#c8d6e8] leading-relaxed">
            Based on a refined Probability of Collision (2.4×10⁻⁴) exceeding the action threshold and an inflated covariance due to minor storm G1, a maneuver is recommended. Plan B offers the most efficient Delta-v expenditure while safely resolving the immediate threat.
          </p>

          <div className="grid grid-cols-2 gap-4 mt-2">
            {/* Plan B (Recommended) */}
            <div className="border-2 border-[#378add] bg-[rgba(55,138,221,0.05)] rounded-lg p-4 flex flex-col gap-3">
              <div className="flex justify-between items-center">
                <span className="font-bold text-[#378add]">Plan B</span>
                <span className="px-2 py-0.5 bg-[#378add]/20 text-[#378add] text-[10px] font-bold uppercase rounded">Recommended</span>
              </div>
              <div className="flex flex-col gap-1 text-xs">
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] pb-1">
                  <span className="text-slate-400">Burn Sequence</span>
                  <span className="text-slate-200">Split burn (0.15m/s, 0.12m/s)</span>
                </div>
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] py-1">
                  <span className="text-slate-400">Total Δv</span>
                  <span className="text-green-500 font-bold">0.27 m/s</span>
                </div>
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] py-1">
                  <span className="text-slate-400">Events Resolved</span>
                  <span className="text-green-500 font-bold">1/1</span>
                </div>
                <div className="flex justify-between pt-1">
                  <span className="text-slate-400">Residual Pc</span>
                  <span className="text-slate-200">8.2×10⁻⁷</span>
                </div>
              </div>
            </div>

            {/* Plan A (Alternative) */}
            <div className="border border-mission-border bg-mission-panel rounded-lg p-4 flex flex-col gap-3">
              <div className="flex justify-between items-center">
                <span className="font-bold text-slate-200">Plan A</span>
                <span className="text-slate-500 text-[10px] font-bold uppercase">Alternative</span>
              </div>
              <div className="flex flex-col gap-1 text-xs">
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] pb-1">
                  <span className="text-slate-400">Burn Sequence</span>
                  <span className="text-slate-200">Single burn (0.35m/s)</span>
                </div>
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] py-1">
                  <span className="text-slate-400">Total Δv</span>
                  <span className="text-amber-500 font-bold">0.35 m/s</span>
                </div>
                <div className="flex justify-between border-b border-[rgba(255,255,255,0.06)] py-1">
                  <span className="text-slate-400">Events Resolved</span>
                  <span className="text-green-500 font-bold">1/1</span>
                </div>
                <div className="flex justify-between pt-1">
                  <span className="text-slate-400">Residual Pc</span>
                  <span className="text-slate-200">3.1×10⁻⁷</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex gap-3 mt-4">
            <button 
              onClick={() => handleApprove("B")}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white font-bold rounded transition-colors"
            >
              Approve Plan B
            </button>
            <button 
              onClick={() => handleApprove("A")}
              className="px-4 py-2 border border-mission-border bg-mission-panel hover:bg-white/5 text-slate-200 rounded transition-colors"
            >
              Approve Plan A instead
            </button>
            <button 
              onClick={() => {
                toast("Maneuver rejected. No action taken.");
                onNavigate("dashboard");
              }}
              className="px-4 py-2 border border-mission-border bg-mission-panel hover:bg-white/5 text-slate-200 rounded transition-colors ml-auto"
            >
              Reject — do nothing
            </button>
          </div>
        </div>

        {/* Plan evaluation table */}
        <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
          <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)]">
            <span>Plan Evaluation</span>
          </div>
          <div className="flex flex-col">
            <div className="flex px-4 py-2 bg-[#060b14] text-[#3a5060] text-[10px] uppercase border-b border-[rgba(255,255,255,0.06)]">
              <div className="flex-1">Event</div>
              <div className="w-[20%]">Baseline Pc</div>
              <div className="w-[20%]">Pc after Plan B</div>
              <div className="w-[20%]">Pc after Plan A</div>
            </div>
            
            <div className="flex items-center px-4 py-3 border-b border-[rgba(255,255,255,0.06)] text-xs">
              <div className="flex-1 text-slate-200 font-bold">SL-4521 / Cosmos DEB 33759</div>
              <div className="w-[20%] text-red-500 font-mono">2.4×10⁻⁴</div>
              <div className="w-[20%] text-green-500 font-mono">8.2×10⁻⁷</div>
              <div className="w-[20%] text-green-500 font-mono">3.1×10⁻⁷</div>
            </div>

            <div className="flex items-center px-4 py-3 text-xs">
              <div className="flex-1 text-slate-400">SL-4521 / Iridium-33 DEB (Future)</div>
              <div className="w-[20%] text-amber-500 font-mono">8.0×10⁻⁵</div>
              <div className="w-[20%] text-slate-500 font-mono">8.0×10⁻⁵</div>
              <div className="w-[20%] text-slate-500 font-mono">8.0×10⁻⁵</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
