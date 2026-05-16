import * as React from "react";
import { useAgentStream, type AgentEvent, type AgentEventType } from "../lib/agentStream";

const TYPE_LABEL: Record<AgentEventType, string> = {
  thought: "thinks",
  tool_call: "calls",
  tool_result: "result",
  heartbeat: "idle",
  verdict_drafted: "verdict",
};

const TYPE_COLOR: Record<AgentEventType, string> = {
  thought: "text-[#7a9ab0]",
  tool_call: "text-cyan-400",
  tool_result: "text-emerald-400",
  heartbeat: "text-[#3a5060]",
  verdict_drafted: "text-amber-400",
};

const EMPTY_HINT = "Awaiting agent activity. Start the runner sidecar to see live reasoning.";

function formatContent(ev: AgentEvent): string {
  if (typeof ev.content === "string") return ev.content;
  const c = ev.content as { name?: string; args?: string; summary?: string };
  if (ev.type === "tool_call") {
    return `${c.name ?? "?"}(${c.args ?? ""})`;
  }
  if (ev.type === "tool_result") {
    return `${c.name ?? "?"} → ${c.summary ?? ""}`;
  }
  if (ev.type === "verdict_drafted") {
    return `${c.name ?? "draft_recommendation"} fired`;
  }
  return JSON.stringify(c);
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return "--:--:--";
  }
}

export function AgentReasoningStream() {
  const events = useAgentStream();
  const scrollerRef = React.useRef<HTMLDivElement>(null);

  // Keep the latest event in view as new ones arrive.
  React.useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div
      ref={scrollerRef}
      className="flex flex-col gap-1 p-4 bg-[#060b14] rounded-b-lg text-xs font-mono w-full h-[260px] overflow-y-auto"
    >
      {events.length === 0 ? (
        <span className="text-[#3a5060] italic">{EMPTY_HINT}</span>
      ) : (
        events.map((ev) => (
          <div key={ev._seq} className="flex gap-2 items-start">
            <span className="text-[#3a5060] shrink-0 tabular-nums">
              {formatTimestamp(ev.timestamp)}
            </span>
            <span className={`shrink-0 uppercase ${TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"}`}>
              {TYPE_LABEL[ev.type] ?? ev.type}
            </span>
            <span className={TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"}>
              {formatContent(ev)}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
