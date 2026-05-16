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

const EMPTY_HINT_GLOBAL = "Awaiting agent activity. Start the runner sidecar to see live reasoning.";
const EMPTY_HINT_FILTERED = "No reasoning yet for this conjunction. Agent will pick it up when it reaches this event.";

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

/**
 * Reasoning models (Nemotron included) demarcate their final answer with
 * `\boxed{...}` in the chain-of-thought. Pull the inner value out so the UI
 * can render those moments distinctly.
 *
 * Returns the inner string (e.g. "dismissed", "watch", "recommended", "Plan B")
 * or null if no boxed answer is present.
 */
function extractBoxedAnswer(content: string): string | null {
  const m = content.match(/\\boxed\{([^}]+)\}/);
  if (!m || m[1] === undefined) return null;
  return m[1].trim();
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return "--:--:--";
  }
}

export interface AgentReasoningStreamProps {
  /**
   * If set, only show events whose related_event_id matches. Used by
   * ConjunctionDetailView to scope the stream to one conjunction. Leave
   * undefined for the global dashboard panel (shows everything).
   */
  eventId?: string;
  /** Height override; defaults to h-[260px] for the detail view. */
  className?: string;
}

export function AgentReasoningStream({ eventId, className }: AgentReasoningStreamProps = {}) {
  const events = useAgentStream();
  const scrollerRef = React.useRef<HTMLDivElement>(null);

  const filtered = React.useMemo(() => {
    if (!eventId) return events;
    return events.filter((ev) => ev.related_event_id === eventId);
  }, [events, eventId]);

  // Keep the latest event in view as new ones arrive.
  React.useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [filtered.length]);

  const emptyHint = eventId ? EMPTY_HINT_FILTERED : EMPTY_HINT_GLOBAL;

  return (
    <div
      ref={scrollerRef}
      className={
        className ??
        "flex flex-col gap-1 p-4 bg-[#060b14] rounded-b-lg text-xs font-mono w-full h-[260px] overflow-y-auto"
      }
    >
      {filtered.length === 0 ? (
        <span className="text-[#3a5060] italic">{emptyHint}</span>
      ) : (
        filtered.map((ev) => {
          const text = formatContent(ev);
          const boxed = extractBoxedAnswer(text);
          if (boxed) {
            return (
              <div
                key={ev._seq}
                className="flex gap-2 items-start rounded-md px-2 py-1.5 bg-amber-500/10 border-l-2 border-amber-400"
              >
                <span className="text-[#3a5060] shrink-0 tabular-nums">
                  {formatTimestamp(ev.timestamp)}
                </span>
                <span className="shrink-0 uppercase text-amber-400 font-bold tracking-wider">
                  FINAL
                </span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-amber-300 font-bold text-sm">
                    {boxed}
                  </span>
                  <span className="text-[#7a9ab0] text-[10px] truncate">
                    {text.replace(/\\boxed\{[^}]+\}/, "").trim()}
                  </span>
                </div>
              </div>
            );
          }
          return (
            <div key={ev._seq} className="flex gap-2 items-start">
              <span className="text-[#3a5060] shrink-0 tabular-nums">
                {formatTimestamp(ev.timestamp)}
              </span>
              <span className={`shrink-0 uppercase ${TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"}`}>
                {TYPE_LABEL[ev.type] ?? ev.type}
              </span>
              <span className={TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"}>
                {text}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}
