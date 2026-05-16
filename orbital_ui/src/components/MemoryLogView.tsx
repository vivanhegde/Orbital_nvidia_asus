import * as React from "react";

const MEMORY_RECORDS = [
  { id: 1, type: "executed", text: "Plan B approved and applied. 3/3 conjunctions resolved.", time: "Just now" },
  { id: 2, type: "approved", text: "Flight director approved Plan B (0.27 m/s split burn).", time: "Just now" },
  { id: 3, type: "recommended", text: "Plan B recommended. Refined Pc 2.4×10⁻⁴ after ×1.18 inflation.", time: "1 min ago" },
  { id: 4, type: "dismissed", text: "Re-screen Pc dropped to 8×10⁻⁷. Dismissed.", time: "2d ago" },
  { id: 5, type: "dismissed", text: "Re-screen Pc dropped to 2×10⁻⁶. Dismissed.", time: "9d ago" },
  { id: 6, type: "executed", text: "Single burn 0.22 m/s executed. Conjunction resolved.", time: "23d ago" },
];

export interface MemoryLogViewProps {
  onNavigate: (view: "dashboard" | "approver" | "memory") => void;
}

export function MemoryLogView({ onNavigate }: MemoryLogViewProps) {
  const [assetFilter, setAssetFilter] = React.useState("SL-4521");
  const [typeFilter, setTypeFilter] = React.useState("all");

  const filteredRecords = MEMORY_RECORDS.filter(r => typeFilter === "all" || r.type === typeFilter);

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
          <span className="cursor-pointer hover:text-slate-200" onClick={() => onNavigate("approver")}>Approver</span>
          <span className="text-white cursor-pointer">Memory</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-xs">SQLite · {MEMORY_RECORDS.length} events logged</span>
        </div>
      </div>

      <div className="bg-mission-panel border border-mission-border rounded-lg flex flex-col overflow-hidden">
        <div className="px-[14px] py-[8px] border-b border-mission-border bg-[rgba(255,255,255,0.02)]">
          <span>Asset Memory Log</span>
        </div>
        
        <div className="p-[14px] flex flex-col gap-[14px]">
          {/* Filter Bar */}
          <div className="flex gap-4 items-center">
            <input 
              type="text" 
              value={assetFilter}
              onChange={(e) => setAssetFilter(e.target.value)}
              placeholder="Filter by Asset ID..."
              className="bg-[#060b14] border border-mission-border rounded px-3 py-1.5 text-slate-200 focus:outline-none focus:border-slate-500 w-64"
            />
            <select 
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-[#060b14] border border-mission-border rounded px-3 py-1.5 text-slate-200 focus:outline-none focus:border-slate-500 w-48"
            >
              <option value="all">All Events</option>
              <option value="recommended">Recommended</option>
              <option value="approved">Approved</option>
              <option value="executed">Executed</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </div>

          {/* Event Log Panel */}
          <div className="flex flex-col border border-mission-border bg-[#060b14] rounded overflow-hidden">
            {filteredRecords.map((r, i) => {
              const badgeColor = 
                r.type === "executed" ? "bg-[#378add]/20 text-[#378add]" :
                r.type === "approved" ? "bg-green-500/20 text-green-500" :
                r.type === "recommended" ? "bg-amber-500/20 text-amber-500" :
                "bg-slate-500/20 text-slate-400";
                
              return (
                <div key={r.id} className={`flex items-center gap-4 p-3 border-b border-[rgba(255,255,255,0.06)] hover:bg-white/5 transition-colors ${i === filteredRecords.length - 1 ? 'border-b-0' : ''}`}>
                  <div className="w-[100px] shrink-0">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase ${badgeColor}`}>
                      {r.type}
                    </span>
                  </div>
                  <div className="flex-1 text-[#c8d6e8]">{r.text}</div>
                  <div className="w-[80px] shrink-0 text-right text-[#3a5060] text-xs">{r.time}</div>
                </div>
              );
            })}
            {filteredRecords.length === 0 && (
              <div className="p-6 text-center text-slate-500">No records found matching filters.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
