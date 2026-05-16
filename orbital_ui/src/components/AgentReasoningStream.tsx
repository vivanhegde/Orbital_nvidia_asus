import * as React from "react";
import { useAgentStream, type AgentEvent, type AgentEventType } from "../lib/agentStream";

// ── Visual taxonomy ───────────────────────────────────────────────────────

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

const THOUGHT_PREVIEW_CHARS = 180;

// ── Helpers ───────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return "--:--:--";
  }
}

/** Strip the `orbital__` MCP-server prefix so the bare tool name shows. */
function stripPrefix(name: string): string {
  return name.includes("__") ? name.split("__").slice(-1)[0]! : name;
}

/** Parse a tool-call args string (which the forwarder serialises as JSON) into an object. */
function parseArgs(argsStr: string | undefined): Record<string, unknown> {
  if (!argsStr) return {};
  try {
    const parsed = JSON.parse(argsStr) as unknown;
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/**
 * Convert a raw tool invocation into a one-line operator-readable sentence.
 *
 *   orbital__get_space_weather({})              → "Checking current space weather"
 *   orbital__re_propagate({"norad_id":44714})   → "Re-propagating NORAD 44714 with latest TLE"
 *
 * Falls back to "callname(json…)" if the tool isn't in the catalog.
 */
function humanizeToolCall(name: string, argsStr: string | undefined): string {
  const tool = stripPrefix(name);
  const args = parseArgs(argsStr);
  const num = (k: string) => (typeof args[k] === "number" ? (args[k] as number) : undefined);
  const str = (k: string) => (typeof args[k] === "string" ? (args[k] as string) : undefined);

  switch (tool) {
    case "get_space_weather":
      return "Checking current space weather (Kp / X-ray / storm level)";
    case "get_object_metadata": {
      const n = num("norad_id");
      return n !== undefined ? `Looking up NORAD ${n} metadata` : "Looking up object metadata";
    }
    case "get_flagged_conjunctions":
      return "Pulling currently flagged conjunctions";
    case "get_conjunctions_for_asset": {
      const n = num("norad_id");
      return n !== undefined
        ? `Listing upcoming conjunctions for NORAD ${n}`
        : "Listing upcoming conjunctions for asset";
    }
    case "query_memory": {
      const n = num("norad_id");
      const e = str("event_id");
      if (e) return `Querying memory for event ${e.slice(0, 8)}…`;
      if (n !== undefined) return `Querying memory for NORAD ${n}`;
      return "Querying memory";
    }
    case "write_memory": {
      const vt = str("verdict_type");
      return vt ? `Recording verdict: ${vt}` : "Recording verdict";
    }
    case "re_propagate": {
      const n = num("norad_id");
      const at = str("at_iso");
      if (n !== undefined) {
        return at
          ? `Re-propagating NORAD ${n} to ${at.slice(0, 19).replace("T", " ")}`
          : `Re-propagating NORAD ${n} with latest TLE`;
      }
      return "Re-propagating object with latest TLE";
    }
    case "compute_collision_probability": {
      const a = num("norad_id_a");
      const b = num("norad_id_b");
      if (a !== undefined && b !== undefined) {
        return `Computing refined Pc: NORAD ${a} vs ${b}`;
      }
      return "Computing refined collision probability";
    }
    case "simulate_maneuver": {
      const n = num("norad_id");
      const dv = num("dv_mps");
      const dir = str("direction");
      if (n !== undefined && dv !== undefined && dir) {
        return `Simulating ${dv.toFixed(2)} m/s ${dir} burn on NORAD ${n}`;
      }
      return "Simulating maneuver";
    }
    case "evaluate_plan": {
      const n = num("asset_norad_id");
      return n !== undefined
        ? `Evaluating maneuver plan for NORAD ${n}`
        : "Evaluating maneuver plan";
    }
    case "draft_recommendation":
      return "Drafting maneuver recommendation";
    default:
      return `${tool}(${argsStr ?? ""})`;
  }
}

/** Truncate a long thought to the first sentence (or `maxChars`), with ellipsis. */
function truncateThought(text: string, maxChars: number): { preview: string; truncated: boolean } {
  const clean = text.trim();
  if (clean.length <= maxChars) return { preview: clean, truncated: false };
  // Prefer cutting at a sentence boundary if one is within the first maxChars.
  const slice = clean.slice(0, maxChars);
  const lastBreak = Math.max(slice.lastIndexOf(". "), slice.lastIndexOf(".\n"));
  if (lastBreak > 60) {
    return { preview: slice.slice(0, lastBreak + 1), truncated: true };
  }
  return { preview: slice, truncated: true };
}

function extractVerdict(ev: AgentEvent): string | null {
  if (ev.type !== "verdict_drafted") return null;
  if (typeof ev.content === "string") return ev.content;
  const c = ev.content as { verdict_type?: string };
  return c.verdict_type ?? null;
}

function extractBoxedAnswer(content: string): string | null {
  const m = content.match(/\\{1,2}boxed\{([^}]+)\}/);
  if (!m || m[1] === undefined) return null;
  return m[1].trim();
}

// ── Row renderers ─────────────────────────────────────────────────────────
//
// Each row is a 3-column grid: [time | TYPE | content]. The container is the
// grid parent; each row emits its 3 cells either as a React.Fragment (regular
// rows) or as a single col-span-3 cell (FinalRow gets a full-width highlight).

const TIME_CELL = "text-[#3a5060] tabular-nums text-[11px] pt-0.5";
const TYPE_CELL_BASE = "uppercase font-bold text-[10px] tracking-wider text-right pt-0.5 pr-1";

function TypeChip({ label, color }: { label: string; color: string }) {
  return <span className={`${TYPE_CELL_BASE} ${color}`}>{label}</span>;
}

function ThoughtRow({ ev }: { ev: AgentEvent }) {
  const [expanded, setExpanded] = React.useState(false);
  const raw = typeof ev.content === "string" ? ev.content : JSON.stringify(ev.content);
  const { preview, truncated } = truncateThought(raw, THOUGHT_PREVIEW_CHARS);
  return (
    <>
      <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
      <TypeChip label="THINKS" color="text-[#7a9ab0]" />
      <span className="text-[#7a9ab0] leading-snug min-w-0">
        {expanded || !truncated ? raw : preview}
        {truncated && (
          <button
            type="button"
            onClick={() => setExpanded((x) => !x)}
            className="ml-1.5 text-[#3a5060] hover:text-cyan-400 text-[10px]"
          >
            {expanded ? "[collapse]" : "[…more]"}
          </button>
        )}
      </span>
    </>
  );
}

function ToolCallRow({ ev }: { ev: AgentEvent }) {
  const c = typeof ev.content === "string" ? { name: ev.content, args: "" } : (ev.content as { name?: string; args?: string });
  const sentence = humanizeToolCall(c.name ?? "?", c.args);
  return (
    <>
      <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
      <TypeChip label="CALLS" color="text-cyan-400" />
      <span className="text-cyan-300 leading-snug min-w-0">→ {sentence}</span>
    </>
  );
}

function ToolResultRow({ ev }: { ev: AgentEvent }) {
  const c = typeof ev.content === "string" ? { name: "", summary: ev.content } : (ev.content as { name?: string; summary?: string });
  const toolShort = c.name ? stripPrefix(c.name) : "tool";
  return (
    <>
      <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
      <TypeChip label="RESULT" color="text-emerald-400" />
      <span className="text-emerald-300 leading-snug min-w-0">
        <span className="text-[#3a5060]">{toolShort}:</span> {c.summary ?? "(empty)"}
      </span>
    </>
  );
}

function HeartbeatRow({ ev }: { ev: AgentEvent }) {
  const text = typeof ev.content === "string" ? ev.content : JSON.stringify(ev.content);
  return (
    <>
      <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
      <TypeChip label="IDLE" color="text-[#3a5060]" />
      <span className="text-[#3a5060] leading-snug min-w-0">{text}</span>
    </>
  );
}

function FinalRow({
  ev,
  verdict,
  trailingThought,
  onNavigate,
}: {
  ev: AgentEvent;
  verdict: string;
  trailingThought?: string;
  onNavigate?: (view: "dashboard" | "approver" | "memory") => void;
}) {
  const isRecommended = verdict.toLowerCase().startsWith("recommend");
  return (
    <div
      className={`col-span-3 grid grid-cols-[68px_60px_1fr] gap-x-2 items-start rounded-md px-2 py-1.5 ${
        isRecommended
          ? "bg-amber-500/15 border-l-4 border-amber-400"
          : "bg-amber-500/[0.08] border-l-2 border-amber-400"
      }`}
    >
      <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
      <TypeChip label="FINAL" color="text-amber-400" />
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-amber-300 font-bold text-sm uppercase">{verdict}</span>
          {isRecommended && onNavigate && (
            <button
              type="button"
              onClick={() => onNavigate("approver")}
              className="px-2 py-0.5 rounded bg-amber-500/30 hover:bg-amber-500/50 text-amber-200 text-[10px] font-bold tracking-wider transition"
            >
              OPEN APPROVER →
            </button>
          )}
          {isRecommended && (
            <span className="text-[10px] text-amber-200/70 italic">
              Operator action required
            </span>
          )}
        </div>
        {trailingThought && (
          <span className="text-[#7a9ab0] text-[10px] truncate">{trailingThought}</span>
        )}
      </div>
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────

export interface AgentReasoningStreamProps {
  /**
   * If set, only show events whose related_event_id matches. Used by
   * ConjunctionDetailView to scope the stream to one conjunction. Leave
   * undefined for the global dashboard panel.
   */
  eventId?: string;
  /** Height override; defaults to h-[260px] for the detail view. */
  className?: string;
  /**
   * If set, FINAL rows with a "recommended" verdict show an "Open Approver"
   * button that calls this with the target view name.
   */
  onNavigate?: (view: "dashboard" | "approver" | "memory") => void;
}

export function AgentReasoningStream({
  eventId,
  className,
  onNavigate,
}: AgentReasoningStreamProps = {}) {
  const events = useAgentStream();
  const scrollerRef = React.useRef<HTMLDivElement>(null);

  const filtered = React.useMemo(() => {
    if (!eventId) return events;
    return events.filter((ev) => ev.related_event_id === eventId);
  }, [events, eventId]);

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
        "grid grid-cols-[68px_60px_1fr] gap-x-2 gap-y-0.5 p-3 bg-[#060b14] rounded-b-lg text-xs font-mono w-full h-[260px] overflow-y-auto auto-rows-min content-start"
      }
    >
      {filtered.length === 0 ? (
        <span className="col-span-3 text-[#3a5060] italic">{emptyHint}</span>
      ) : (
        filtered.map((ev) => {
          // Detect FINAL rows first — they take precedence over per-type render.
          const verdictExplicit = extractVerdict(ev);
          const rawText = typeof ev.content === "string" ? ev.content : "";
          const verdict = verdictExplicit ?? extractBoxedAnswer(rawText);
          if (verdict) {
            const trailing =
              !verdictExplicit && rawText
                ? rawText.replace(/\\{1,2}boxed\{[^}]+\}/, "").trim()
                : undefined;
            return (
              <FinalRow
                key={ev._seq}
                ev={ev}
                verdict={verdict}
                trailingThought={trailing}
                onNavigate={onNavigate}
              />
            );
          }
          switch (ev.type) {
            case "thought":
              return <React.Fragment key={ev._seq}><ThoughtRow ev={ev} /></React.Fragment>;
            case "tool_call":
              return <React.Fragment key={ev._seq}><ToolCallRow ev={ev} /></React.Fragment>;
            case "tool_result":
              return <React.Fragment key={ev._seq}><ToolResultRow ev={ev} /></React.Fragment>;
            case "heartbeat":
              return <React.Fragment key={ev._seq}><HeartbeatRow ev={ev} /></React.Fragment>;
            default:
              return (
                <React.Fragment key={ev._seq}>
                  <span className={TIME_CELL}>{formatTimestamp(ev.timestamp)}</span>
                  <TypeChip
                    label={(TYPE_LABEL[ev.type] ?? ev.type).toUpperCase()}
                    color={TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"}
                  />
                  <span className={`${TYPE_COLOR[ev.type] ?? "text-[#7a9ab0]"} leading-snug min-w-0`}>
                    {typeof ev.content === "string" ? ev.content : JSON.stringify(ev.content)}
                  </span>
                </React.Fragment>
              );
          }
        })
      )}
    </div>
  );
}
