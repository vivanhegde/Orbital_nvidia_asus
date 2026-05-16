import * as React from "react";
import type { AgentBusEvent } from "@/lib/agentBus";

const DEMO_STEPS = [
  "Acknowledged high-risk conjunction event.",
  "Fetching object metadata and historical maneuvers…",
  "Querying historical operator decisions for similar pairs…",
  "Re-propagating orbit trajectories with latest SGP4 TLEs…",
  "Evaluating atmospheric drag models against current Kp index…",
  "Computing refined Probability of Collision (Pc)…",
  "Threshold exceeded. Escalating to URGENT review queue.",
];

export interface AgentReasoningStreamProps {
  /** When set, subscribe to `/api/agent/stream` and show bus events (and heartbeats). */
  relatedEventId?: string | null;
  /** If false and no SSE, run the scripted demo animation instead of an empty panel. */
  useDemoFallback?: boolean;
}

export function AgentReasoningStream({
  relatedEventId,
  useDemoFallback = true,
}: AgentReasoningStreamProps) {
  const [liveLines, setLiveLines] = React.useState<
    Array<{ key: string; text: string; kind: "live" | "heartbeat" | "error" }>
  >([]);
  const [sseConnected, setSseConnected] = React.useState(false);

  React.useEffect(() => {
    const qs = relatedEventId
      ? `?related_event_id=${encodeURIComponent(relatedEventId)}`
      : "";
    const url = `/api/agent/stream${qs}`;
    const es = new EventSource(url);

    es.onopen = () => setSseConnected(true);
    es.onerror = () => setSseConnected(false);

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as AgentBusEvent;
        const type = data.type ?? "event";
        const isErr = type.includes("error");
        const isHb = type === "heartbeat";
        const text = `[${type}] ${data.content}`;
        setLiveLines((prev) => {
          const row = {
            key: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
            text,
            kind: (isErr ? "error" : isHb ? "heartbeat" : "live") as
              | "live"
              | "heartbeat"
              | "error",
          };
          const next = [...prev, row];
          return next.slice(-120);
        });
      } catch {
        /* ignore malformed chunks */
      }
    };

    return () => {
      es.close();
      setSseConnected(false);
    };
  }, [relatedEventId]);

  const [demoIndex, setDemoIndex] = React.useState(0);
  const [demoText, setDemoText] = React.useState("");

  React.useEffect(() => {
    if (!useDemoFallback || liveLines.length > 0 || sseConnected) return;
    if (demoIndex >= DEMO_STEPS.length) return;

    const target = DEMO_STEPS[demoIndex] ?? "";
    if (demoText === target) {
      const t = setTimeout(() => {
        setDemoIndex((s) => s + 1);
        setDemoText("");
      }, 600);
      return () => clearTimeout(t);
    }

    const t = setTimeout(() => {
      setDemoText(target.slice(0, demoText.length + 1));
    }, 25);
    return () => clearTimeout(t);
  }, [demoIndex, demoText, liveLines.length, sseConnected, useDemoFallback]);

  const showDemo =
    useDemoFallback && liveLines.length === 0 && !sseConnected && demoIndex < DEMO_STEPS.length;

  return (
    <div className="flex flex-col gap-2 p-4 bg-[#060b14] rounded-b-lg text-xs font-mono w-full min-h-[180px] max-h-[320px] overflow-y-auto">
      {liveLines.length > 0 && (
        <div className="text-[10px] text-slate-500 border-b border-[rgba(255,255,255,0.06)] pb-2 mb-1">
          Live bus {relatedEventId ? `(event ${relatedEventId.slice(0, 8)}…)` : "(all events)"}
          {sseConnected ? <span className="text-green-500 ml-2">● SSE</span> : <span className="text-amber-600 ml-2">○ reconnecting</span>}
        </div>
      )}
      {liveLines.map((row, i) => (
        <div
          key={row.key}
          className={`flex gap-3 transition-opacity duration-300 ${
            row.kind === "error"
              ? "text-red-400"
              : row.kind === "heartbeat"
                ? "text-slate-500"
                : "text-[#7a9ab0]"
          }`}
        >
          <span className="text-[#3a5060] font-bold shrink-0">{i + 1}.</span>
          <span>{row.text}</span>
        </div>
      ))}
      {liveLines.length === 0 && sseConnected && (
        <p className="text-slate-500 text-xs px-1">Connected to agent bus — waiting for events…</p>
      )}
      {liveLines.length === 0 && showDemo &&
        DEMO_STEPS.map((step, i) => {
          if (i > demoIndex) return null;
          const isActive = i === demoIndex;
          const text = isActive ? demoText : step;
          return (
            <div
              key={i}
              className={`flex gap-3 transition-opacity duration-300 ${
                isActive && demoText.length === 0 ? "opacity-0" : "opacity-100"
              }`}
            >
              <span className="text-[#3a5060] font-bold shrink-0">{i + 1}.</span>
              <span className={isActive ? "text-amber-400" : "text-[#7a9ab0]"}>
                {text}
                {isActive && (
                  <span
                    className="inline-block w-1.5 h-3 bg-amber-400 ml-1 animate-pulse"
                    style={{ verticalAlign: "baseline", marginBottom: "-2px" }}
                  />
                )}
              </span>
            </div>
          );
        })}
      {liveLines.length === 0 && !showDemo && !useDemoFallback && (
        <p className="text-slate-500 text-xs">Waiting for agent events…</p>
      )}
    </div>
  );
}
