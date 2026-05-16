import * as React from "react";

export type AgentEventType =
  | "thought"
  | "tool_call"
  | "tool_result"
  | "heartbeat"
  | "verdict_drafted";

export interface AgentEvent {
  type: AgentEventType;
  content: string | { name?: string; args?: string; summary?: string };
  related_event_id?: string | null;
  timestamp: string;
  /** Local-only sequence id assigned on receipt for stable React keys. */
  _seq: number;
}

const MAX_BUFFERED = 100;
const RECONNECT_DELAY_MS = 2_000;

/**
 * Subscribe to the agent reasoning SSE stream at /api/agent/stream.
 *
 * Returns the most recent `MAX_BUFFERED` events in arrival order.
 * Auto-reconnects on transport drop (every 2s) without resetting the
 * existing buffer — so a flaky connection doesn't wipe the UI's history.
 */
export function useAgentStream(): AgentEvent[] {
  const [events, setEvents] = React.useState<AgentEvent[]>([]);
  const seqRef = React.useRef(0);

  React.useEffect(() => {
    let source: EventSource | null = null;
    let cancelled = false;
    let reconnectTimer: number | undefined;

    const connect = () => {
      if (cancelled) return;
      source = new EventSource("/api/agent/stream");
      source.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data) as Omit<AgentEvent, "_seq">;
          const seq = ++seqRef.current;
          const enriched: AgentEvent = { ...payload, _seq: seq };
          setEvents((prev) => {
            const next = [...prev, enriched];
            return next.length > MAX_BUFFERED
              ? next.slice(next.length - MAX_BUFFERED)
              : next;
          });
        } catch {
          // Malformed line — silently drop. The producer should never emit
          // bad JSON; if it does, fixing the producer is the right move.
        }
      };
      source.onerror = () => {
        source?.close();
        source = null;
        if (!cancelled) {
          reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      source?.close();
    };
  }, []);

  return events;
}
