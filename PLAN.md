# Orbital — Finalized Build Plan

Synthesized from `OrbitalProjectOverview.pdf` and `OrbitalAgent.pdf` against the
state of this repo on `main`. Pre-hackathon prep, OpenAI/Claude API fallbacks,
scope cuts, and the 24-hour schedule are intentionally out of scope — this
document is the technical build plan for the agent and the integration glue
that wires it into the existing system.

---

## 0. Baseline — What Already Exists

The Engine, Data, Persistence, API, and UI layers are largely built. Everything
the agent needs to *read* is in place. The only things missing are (a) the
agent itself, (b) the transport that lets the agent talk to the UI, and (c) the
two tools (`simulate_maneuver`, `evaluate_plan`) that drive the maneuver demo.

| Layer | State | Notes |
|---|---|---|
| `orbital_engine/` — SGP4 propagation, conjunction screening, Pc (2D Gaussian, covariance inflation) | Built | `propagation.py`, `screening.py`, `pc.py`, `models.py` |
| `orbital_data/` — Celestrak TLE fetcher, SATCAT lookup, NOAA SWPC space weather, file-backed JSON cache | Built | 5 TLE groups (`starlink`, `stations`, `fengyun-1c-debris`, `cosmos-2251-debris`, `iridium-33-debris`) cached |
| `orbital_persist/` — SQLite EventStore with 3 tables: `conjunction_events`, `pc_snapshots`, `verdicts` | Built | Migration `001_initial.sql`; `record_screening_pass`, `record_verdict`, `update_operator_decision`, asset/time queries |
| `orbital_api/` — FastAPI: `/api/conjunctions/flagged`, `/api/space-weather`, `/api/memory/*`, `/api/verdicts/*`, `/api/dev/synthesize-verdict`, screening background worker | Built | CORS for `localhost:5173`; `screening_jobs.py` runs the screener |
| `orbital_ui/` — React + Three.js dashboard: Globe, FlaggedEventsList, ConjunctionDetailView, ApproverView (approve/reject), MemoryLogView, KPIStrip, SpaceWeatherBadge, Pc-history chart | Built | `AgentReasoningStream.tsx` exists but is a **hardcoded mock** — no SSE backend wired |
| Agent (Nemotron + reasoning loop + tools + SSE) | **Not built** | This document. |
| `simulate_maneuver`, `evaluate_plan` | **Not built** | Built fresh on top of existing engine primitives (Feature 7). |

**Architecture (revised after verifying what OpenClaw actually is)**

OpenClaw is a Node.js daemon with a WebSocket gateway on `localhost:18789`, not a Python library. There is no `pip install openclaw`. Custom tools are exposed by connecting OpenClaw to an **MCP server** (Model Context Protocol). Our Python code's job is therefore to (a) run an MCP server that exposes the 12 tools, (b) run a sidecar that pokes OpenClaw with kickoff messages, and (c) subscribe to OpenClaw's event stream and forward it as SSE to the React UI.

```
        Ollama daemon (port 11434, OpenAI-compat)
                       ▲
                       │ inference
                       │
        OpenClaw daemon (Node, port 18789, WebSocket gateway)
            ▲                                ▲
            │ kickoff msgs                   │ MCP (stdio or HTTP)
            │ event stream                   │
            │                                │
   orbital_agent/runner.py          orbital_agent/mcp_server.py
   (Python sidecar; polls            (FastMCP server; 12 tools
    SQLite for new events)            wrap orbital_engine / EventStore / API)
            │
            │ POST /api/agent/event   ◄── runner forwards OpenClaw
            ▼                            stream events to the bus
   FastAPI (orbital_api) ──SSE──► React UI (AgentReasoningStream)
            │
            └── existing routes unchanged (verdicts, memory, conjunctions, etc.)
```

**Locked decisions**

| Decision | Value |
|---|---|
| Inference model | `nemotron-3-nano:30b` (verify exact Ollama tag with `ollama pull` day-0) |
| Inference server | Ollama, configured as `llm.type: openai-compatible` with `base_url: http://localhost:11434/v1` in OpenClaw's `agent.yaml` |
| Agent orchestrator | **OpenClaw daemon** (Node 22.14+), default WebSocket gateway `ws://localhost:18789`. Runs as its own process, not embedded in Python. |
| Tool exposure | **MCP server** (FastMCP) — `orbital_agent/mcp_server.py` exposes the 12 tools; OpenClaw connects to it as an MCP client. Tool schemas come from MCP's tool-definition format. |
| Agent config | `agent.yaml` + `SOUL.md` (system prompt) + `AGENTS.md` (agent role) at `orbital_agent/openclaw/` |
| Streaming format | OpenClaw event stream (WebSocket) → re-broadcast as SSE to the UI |
| Memory backend (domain) | Existing SQLite via `orbital_persist.EventStore` for conjunction events + verdicts |
| Memory backend (agent session) | OpenClaw's own `~/.openclaw/workspace/` markdown + SQLite. Namespace clearly — domain memory is ours, session memory is OpenClaw's. |
| Event queue | SQLite polling on `conjunction_events` (no in-memory queue, no Redis) |

**Known risk:** OpenClaw and NemoClaw are explicitly alpha. NemoClaw's docs warn against production use. For a hackathon demo this is acceptable; Feature 1 frontloads the integration test so we discover gateway/MCP wiring problems before depending on them.

The design doc's §7 claim that memory is "a single SQLite table" is wrong — the real schema is three tables (already built and indexed). No migration is required. `query_memory` and `write_memory` map onto `EventStore` methods as specified below.

---

## Feature 1 — OpenClaw daemon + Ollama backend + Python sidecar scaffolding

**Goal:** OpenClaw runs as a configured Node daemon pointed at Ollama, and the
`orbital_agent/` Python package can (a) connect to OpenClaw's WebSocket
gateway, (b) send a kickoff message, and (c) consume the streamed event log.
No tool integration yet — that's Feature 2.

**Install prerequisites (one-time)**
- Node 22.14+ (OpenClaw runtime)
- `npm install -g openclaw` (or whatever the official install path is — verify against OpenClaw docs)
- Ollama running locally with the model pulled: `ollama pull nemotron-3-nano:30b` (verify the exact tag with `ollama list`; the design doc's `Nemotron-3-Nano-30B-A3B-FP8` may not exist as an Ollama tag — fall back to whatever Nemotron Nano variant Ollama actually serves)

**Files to create**

OpenClaw configuration (lives in `orbital_agent/openclaw/`):
- `agent.yaml`:
  ```yaml
  llm:
    type: openai-compatible
    base_url: http://localhost:11434/v1
    model: nemotron-3-nano:30b
  gateway:
    host: 127.0.0.1
    port: 18789
  limits:
    max_tool_calls_per_turn: 25
  mcp_servers:
    - name: orbital
      transport: stdio
      command: python -m orbital_agent.mcp_server   # Feature 2 implements this
  ```
- `SOUL.md` — system prompt (verbatim from design doc §5; populated in Feature 3)
- `AGENTS.md` — agent role / persona (one paragraph: "Orbital is a flight-dynamics analyst…")
- `README.md` — how to start the daemon: `openclaw run --config agent.yaml`

Python side:
- `orbital_agent/__init__.py`
- `orbital_agent/config.py` — env-driven config (`ORBITAL_MODEL`, `OLLAMA_BASE_URL`, `DB_PATH`, `API_BASE_URL`, `HEARTBEAT_SECONDS`, `LOG_LEVEL`, `OPENCLAW_GATEWAY_URL` default `ws://localhost:18789`)
- `orbital_agent/gateway.py` — async WebSocket client for OpenClaw's gateway. Exposes:
  - `send_kickoff(text: str, conversation_id: str | None = None) -> str` — start an investigation; returns a conversation/turn ID
  - `subscribe_events() -> AsyncIterator[dict]` — yields the gateway's event stream (assistant text chunks, tool-call announcements, tool-result confirmations, errors). Used by Feature 5.
  - Auto-reconnect with backoff.
- `orbital_agent/__main__.py` — entrypoint: `python -m orbital_agent`, supports `--smoke` and `--run`
- `orbital_agent/requirements.txt` — `httpx`, `websockets`, `pydantic`, `mcp` (for the FastMCP server in Feature 2)

**Day-0 integration smoke test (frontloaded — blocks all other features)**

`python -m orbital_agent --smoke` does exactly this end-to-end check:

1. Verifies Ollama responds: `GET http://localhost:11434/api/tags` includes the configured model
2. Verifies the OpenClaw daemon is reachable: opens a WebSocket to `ws://localhost:18789` and reads the server hello
3. Spawns a tiny throwaway MCP server in-process that exposes one tool `echo(text: str) -> str`
4. Updates `agent.yaml` (or uses a `--config` override) so OpenClaw connects to the throwaway MCP server
5. Sends a kickoff: `"Please call the echo tool with text='hello'."`
6. Reads the event stream until a `tool_call` for `echo` arrives, the result is observed, and the final assistant message includes `hello`
7. Exits 0 on success

This proves: Ollama serves the model, OpenClaw talks to Ollama, OpenClaw discovers our MCP server, the model produces a tool call, the tool result flows back, and we can subscribe to the event stream. Every other feature in this plan depends on those six things working. If any step fails, the day-0 task is to debug that step before moving on.

**Acceptance**
- `python -m orbital_agent --smoke` exits 0 against a live OpenClaw daemon + Ollama
- `gateway.subscribe_events()` cleanly surfaces every event class OpenClaw emits (text chunk, tool call, tool result, errors)
- The OpenClaw daemon comes up cleanly from `openclaw run --config orbital_agent/openclaw/agent.yaml`

**Out of scope:** the real MCP server with 12 tools (Feature 2), prompt content (Feature 3), the SSE bridge into FastAPI (Feature 5).

---

## Feature 2 — MCP server exposing the 11 agent tools

**Goal:** a Python MCP server (`orbital_agent/mcp_server.py`) that OpenClaw
connects to as an MCP client. Each tool is a typed Python function decorated by
FastMCP so its schema, description, and parameter shape are published over MCP.

**Why MCP, not Python introspection:** OpenClaw's extension model is Skills
(markdown plugin packages) and **MCP servers**. We don't get to hand OpenClaw a
list of Python callables. The portable path for custom domain tools is to
publish them via MCP and configure OpenClaw to mount that server.

**`stream_thought` is dropped from the tool list.** OpenClaw natively emits an
event for every assistant text chunk and every tool call. Feature 5 subscribes
to those events and forwards them as SSE. There's no need for the model to call
a `stream_thought` tool — its narration already streams for free. That leaves
**11 tools**, not 12.

**Files to create**
- `orbital_agent/mcp_server.py` — FastMCP server entrypoint. One `mcp = FastMCP("orbital")` instance; each tool decorated with `@mcp.tool()`. Runs over stdio by default (configured via `transport: stdio` in `agent.yaml`).
- `orbital_agent/tools/data.py` — `get_flagged_conjunctions`, `get_object_metadata`, `get_space_weather`, `get_conjunctions_for_asset`
- `orbital_agent/tools/memory.py` — `query_memory`, `write_memory`
- `orbital_agent/tools/analysis.py` — `re_propagate`, `compute_collision_probability`, `simulate_maneuver`, `evaluate_plan`
- `orbital_agent/tools/output.py` — `draft_recommendation`
- `orbital_agent/tools/_pydantic_models.py` — nested-argument models (`DeltaV`, `Burn`, `BurnSequence`, `RecommendationPlan`, etc.) used by FastMCP for schema generation

Each tool function:
- Has fully typed parameters (Pydantic models for nested args)
- Has a one-line docstring (FastMCP publishes it as the tool description)
- Returns a typed value (FastMCP serializes it to MCP's content format)
- Is registered in `mcp_server.py` with `@mcp.tool()`

**Mapping (authoritative — 11 tools)**

| Tool | Implementation | Status |
|---|---|---|
| `get_flagged_conjunctions(since, min_pc, asset_filter)` | HTTP GET `/api/conjunctions/flagged`; filter client-side | Wraps existing API |
| `get_object_metadata(object_id)` | `orbital_data.store.get_satcat_record(norad_id)` + augment with `is_maneuverable`/`fuel_remaining_mps` from `orbital_data/cache/asset_profiles.json` (seed entries only for the demo assets) | Wraps existing store + tiny seed file |
| `get_space_weather()` | HTTP GET `/api/space-weather` | Wraps existing API |
| `get_conjunctions_for_asset(asset_id, horizon_hours)` | HTTP GET `/api/memory/asset/{norad_id}` filtered by TCA window | Wraps existing API |
| `query_memory(asset_id, conjunction_id, limit)` | `EventStore.query_events_for_asset` + `get_verdict` joins | Wraps existing store |
| `write_memory(record)` | `EventStore.record_verdict(...)` | Wraps existing store |
| `re_propagate(object_id, use_latest_tle)` | `orbital_data.store.get_tles(...)` then `orbital_engine.propagation.propagate(tle, now)` | Wraps existing engine |
| `compute_collision_probability(obj1_state, obj2_state, covariance_inflation)` | `orbital_engine.pc.compute_pc(...)` — covariance inflation factor comes from Feature 4's Kp helper if the model omits it | Wraps existing engine |
| `simulate_maneuver(asset_id, delta_v_vector, burn_time)` | Add ΔV vector to the propagated velocity at `burn_time`, re-propagate the modified state forward using real SGP4, return the new state series. Simplification: state carried in-memory, no TLE refit | New (built in Feature 7's `orbital_engine/maneuver.py`) |
| `evaluate_plan(asset_id, burn_sequence)` | Iterate `simulate_maneuver` over the burn sequence, then re-run `orbital_engine.screening.screen_conjunctions` against the modified trajectory; return `{resolved_event_ids, new_event_ids, total_dv_mps, fuel_remaining_mps, residual_max_pc}` | New (Feature 7) |
| `draft_recommendation(asset_id, recommended_plan, alternative_plans, reasoning, urgency)` | Validates the recommendation JSON via a Pydantic model, then `EventStore.record_verdict(event_id, verdict_type="recommended", reasoning, plan=...)` where `plan` is the full spec (primary + alternatives) | Wraps existing store |

**Acceptance**
- `python -m orbital_agent.mcp_server --list-tools` (FastMCP CLI) prints every tool with its MCP schema
- A separate MCP inspector (e.g. `mcp dev orbital_agent/mcp_server.py`) can call `get_space_weather` and `simulate_maneuver` end-to-end
- With the server mounted in `agent.yaml`, OpenClaw's daemon log shows `discovered 11 tools from mcp/orbital` on startup
- `simulate_maneuver` / `evaluate_plan` return plausible numbers when invoked on a real flagged event from the live DB

---

## Feature 3 — Prompts, agent persona, kickoff invocation

**Goal:** wire the reasoning content (system prompt, kickoff template) into
OpenClaw, and provide the Python helper that turns a `conjunction_events` row
into a kickoff message sent over the gateway.

OpenClaw owns the reasoning loop. We do not implement message-history
management, tool dispatch, or assistant-text accumulation — those live in the
OpenClaw daemon.

**Files to create**
- `orbital_agent/openclaw/SOUL.md` — system prompt, verbatim from design doc §5 ("You are Orbital, an autonomous orbital safety analyst…"). OpenClaw loads this automatically.
- `orbital_agent/openclaw/AGENTS.md` — one-paragraph agent persona/role.
- `orbital_agent/prompts/investigate_kickoff.txt` — user-turn template (design doc §5.5):
  ```
  A new conjunction has been flagged.
  Event ID: {event_id}
  Objects: {obj1_name} (NORAD {obj1_id}) vs {obj2_name} (NORAD {obj2_id})
  TCA: {tca}
  Initial miss distance: {miss_km} km
  Initial Pc: {initial_pc}
  Begin your investigation following the protocol. Stream your thoughts as you go.
  ```
- `orbital_agent/kickoff.py` — `build_kickoff(event: ConjunctionEventRecord) -> str` renders the template; `send_kickoff_for_event(event)` calls `gateway.send_kickoff(text)` (Feature 1) and returns the conversation ID.

**Modes**
- The three modes from the design doc (`Idle/Monitor`, `Investigate`, `Plan`) live inside the model's reasoning, not in our code:
  - **Idle/Monitor** = the runner is in its polling loop with no active conversation; heartbeats come from `orbital_agent/heartbeat.py` (Feature 4), not from OpenClaw
  - **Investigate** = an active OpenClaw conversation, started by `send_kickoff_for_event`
  - **Plan** = same conversation continues; the model self-escalates when refined Pc ≥ 1e-4 (per the system-prompt protocol) and starts calling `get_conjunctions_for_asset` / `simulate_maneuver` / `evaluate_plan`
- The 25-tool-call cap is set in `agent.yaml` (`limits.max_tool_calls_per_turn`), not enforced in Python

**Recommendation output contract** (what `draft_recommendation` validates via Pydantic before persisting; design doc §5.5):
```json
{
  "asset_id": "STARLINK-4521",
  "urgency": "act_within_24hr",
  "primary_plan": {
    "name": "...",
    "burns": [{"dv_mps": 0.18, "direction": "prograde", "burn_time": "ISO8601"}],
    "total_dv_mps": 0.27,
    "conjunctions_resolved": ["event-id-1", "event-id-2"]
  },
  "alternative_plans": [...],
  "reasoning": "Plan B resolves all three conjunctions..."
}
```

**Acceptance**
- Worked example from design doc §6 (STARLINK-4521 vs Cosmos-2251 debris, Pc 3.2e-4) runs end-to-end: insert the event row, runner picks it up, gateway emits a stream of events ending in a `draft_recommendation` tool call, verdict row exists in SQLite with both a primary plan and at least one alternative
- ≥ 5 distinct assistant-text events stream from OpenClaw per investigation (matches Definition of Done — replaces "5 stream_thought calls" in the design doc, since narration is now ambient rather than tool-driven)
- Investigation finishes within ~60 s on the target hardware (soft target)

---

## Feature 4 — Event queue, heartbeat, covariance inflation helper

**Goal:** the agent pulls work without anyone pushing to it, and stays visible
on the UI between events.

**Files to create**
- `orbital_agent/runner.py` — outer driver, run as a long-lived sidecar via `python -m orbital_agent --run`. Pseudocode:
  ```python
  async def main():
      gateway = OpenClawGateway(...)             # Feature 1
      bus = AgentEventBridge(api_base_url)       # Feature 5 (POST → /api/agent/event)
      asyncio.create_task(forward_events(gateway, bus))
      asyncio.create_task(heartbeat_loop(bus))
      while True:
          event = next_pending_event(store)
          if event:
              mark_in_progress(event.event_id)
              await send_kickoff_for_event(event)   # Feature 3
              await wait_for_conversation_end(gateway)
              mark_done(event.event_id)
          else:
              await asyncio.sleep(POLL_INTERVAL_S)
  ```
- `orbital_agent/queue.py`
  - `next_pending_event(store: EventStore) -> ConjunctionEventRecord | None` — SQL: events with `status='monitoring'` that have **no verdict** yet (left join `verdicts`), ordered by initial Pc desc, then `first_detected_at` asc
  - `mark_in_progress(event_id)` / `mark_done(event_id)` — in-memory set (one agent process, sequential loop, no race)
- `orbital_agent/heartbeat.py` — every 30 s while no conversation is active, POST a `heartbeat` event to `/api/agent/event` (Feature 5): `"Monitoring {n_objects} objects, {n_watch} in elevated-risk watch, no new flags in last 30s."` Stats come from `/api/catalog/summary` and `/api/memory/recent?status=monitoring`. Heartbeats are runner-side, not model-side — they cost zero tokens.
- `orbital_agent/space_weather.py` — `covariance_inflation_from_kp(kp: float) -> float`:
  - `kp < 5.0` → 1.0
  - `5.0 ≤ kp < 6.0` → 1.18
  - `kp ≥ 6.0` → 1.4
  - The system prompt tells the model to inflate covariance during elevated Kp; `compute_collision_probability` accepts the factor as an argument and the model passes it. This helper defaults it inside the MCP tool if the model omits the argument.

**Acceptance**
- Runner idle: one heartbeat event hits the SSE stream every 30 s
- When a row appears in `conjunction_events` with no verdict, the runner picks it up within one poll interval (default 5 s; configurable) and starts a new OpenClaw conversation
- After OpenClaw signals the conversation has ended (terminal assistant message), the runner returns to polling

---

## Feature 5 — OpenClaw event stream → SSE bridge → UI

**Goal:** real reasoning shows up in `AgentReasoningStream.tsx` instead of the
hardcoded `AGENT_LOGS` mock. The flow is:

```
OpenClaw gateway (WebSocket events)
        │
        ▼
runner.py forwarder ──HTTP POST──▶ /api/agent/event ──▶ AgentBus
                                                              │
                                                              ▼
                                       /api/agent/stream (SSE) ──▶ React UI
```

**Backend (FastAPI)**
- `orbital_api/agent_bus.py` — in-process pub/sub. Class `AgentBus` with `publish(event: dict)` and `subscribe() -> AsyncIterator[dict]`. Single instance, registered in `main.py`'s lifespan
- `orbital_api/routes/agent_route.py`
  - `GET /api/agent/stream` — SSE endpoint, yields `data: <json>\n\n` for each event from `AgentBus.subscribe()`. Uses `sse-starlette` for backpressure
  - `POST /api/agent/event` — internal endpoint the runner POSTs to. Body: `{type, content, related_event_id?, timestamp}`. Adds to bus, returns 204
- Wire route in `orbital_api/main.py`

**Runner side (`orbital_agent/forwarder.py`)**
- `forward_events(gateway, bus_url)` — async task that:
  1. Subscribes to OpenClaw's WebSocket event stream (Feature 1's `gateway.subscribe_events()`)
  2. Normalizes each event into our shape (see below)
  3. POSTs it to `/api/agent/event`
- Maps OpenClaw event classes onto our UI types:
  - assistant text chunk → `{type: "thought", content: chunk_text}`
  - tool call announcement → `{type: "tool_call", content: {name, args}}`
  - tool result → `{type: "tool_result", content: {name, summary}}`
  - draft_recommendation tool call observed → also emit `{type: "verdict_drafted", content: {verdict_id, asset_id}}`
- Heartbeats are POSTed directly by `heartbeat.py` (Feature 4), bypassing OpenClaw

**UI event shape (stable contract)**
```json
{
  "type": "thought" | "tool_call" | "tool_result" | "heartbeat" | "verdict_drafted",
  "content": "string or short object",
  "related_event_id": "evt-xxx",
  "timestamp": "ISO8601"
}
```

**Frontend**
- `orbital_ui/src/lib/agentStream.ts` — `useAgentStream(): AgentEvent[]` React hook backed by `EventSource("/api/agent/stream")`. Buffers last 100 events
- `orbital_ui/src/components/AgentReasoningStream.tsx` — replace hardcoded `AGENT_LOGS` with the live stream; keep the existing visual treatment (auto-scroll, typewriter-style for new lines). Assistant text chunks arrive token-by-token from Ollama through OpenClaw without us doing anything special — they show up as a stream of `thought` events with small `content` strings.

**Acceptance**
- Open the dashboard with the agent + OpenClaw running → the reasoning panel shows live, scrolling output (heartbeats when idle, full investigation flow when an event triggers)
- Token-by-token streaming visibly renders progressively in the UI (not in batches per turn)
- Refreshing the page reconnects cleanly; missed events are not replayed (acceptable for demo)

---

## Feature 6 — Domain memory tools wired to existing EventStore

**Goal:** `query_memory` and `write_memory` (as MCP tools — Feature 2) map
cleanly onto the existing 3-table schema without inventing a parallel store.

**Two memory layers, kept namespaced and separate:**
- **Domain memory** (this feature) — our `orbital_persist.EventStore` at `orbital_data/orbital.db`. Conjunction events, Pc snapshots, verdicts. The model accesses it through `query_memory` / `write_memory` MCP tools.
- **OpenClaw session memory** — OpenClaw maintains its own state at `~/.openclaw/workspace/` (markdown + SQLite). This holds conversation transcripts, agent persona state, and skill-internal memory. We don't touch it from Python; it's OpenClaw's house. The two stores share no schema and do not collide.

**Implementation (domain layer)**
- `query_memory(asset_id, conjunction_id=None, limit=10)`:
  - If `conjunction_id` set: `get_event` + latest verdict
  - Else: `query_events_for_asset(asset_id, limit)` joined with `get_verdict` per event; project to a flat list of `{event_id, tca, miss_km, latest_pc, verdict_type, operator_decision, issued_at}`
- `write_memory(record)`:
  - Translates the agent's `{event_id, verdict_type, reasoning, plan}` into `EventStore.record_verdict(...)`
  - For dismiss/watch verdicts, `plan=None`
- No new tables. No migrations.

**Acceptance**
- `query_memory(asset_id="STARLINK-4521", limit=5)` returns prior events including verdicts when present
- `write_memory({...recommended plan...})` produces a row visible at `/api/verdicts/pending`

---

## Feature 7 — Maneuver simulation + applied-plan → 3D viz

**Goal:** when an operator approves, the satellite's orbit shifts in the
visualization and the resolved conjunctions visibly disappear from the flagged
list. This is the demo's payoff moment.

**Backend**
- `orbital_engine/maneuver.py` — new file
  - `apply_burn(state: PropagatedState, dv_vector_kms: tuple[float,float,float], burn_time: datetime) -> TLE | "synthetic_state"` — for the demo we don't need a re-fit TLE; an in-memory override of the propagated trajectory is enough. Store as `{norad_id: [PropagatedState, ...]}` keyed override applied for the next N minutes of UI polling
  - `apply_plan(plan_json) -> dict[norad_id, override_trajectory]`
- `orbital_api/routes/verdicts_route.py` — extend `POST /api/verdicts/{verdict_id}/approve` to:
  1. Call existing `update_operator_decision`
  2. Call `orbital_engine.maneuver.apply_plan(plan)` and stash the override in `orbital_api/positions.py`
  3. Mark all `plan.conjunctions_resolved` events as `status='resolved'` in `conjunction_events`
- `orbital_api/positions.py` — when serving `/api/catalog/positions`, prefer override trajectories if present and not expired

**Frontend**
- No new component. The Globe already re-polls positions every 5 s; the resolved conjunctions naturally drop out of `FlaggedEventsList` because the API filters by status
- `GlobeView.tsx` — optional polish: brief green pulse on the asset marker on the first frame where override is applied (use a `useEffect` watching for trajectory change)

**Acceptance**
- Approving a recommendation in the Approver View:
  - flips the verdict row to `approved`
  - removes the resolved conjunctions from the flagged list within one poll cycle
  - changes the asset's plotted trajectory subtly in the Globe

---

## Feature 8 — Recommendation flow into the existing Approver View

**Goal:** zero new UI work for the approver flow — agent verdicts must
materialize as rows that `ApproverView.tsx` already renders.

**Implementation**
- `draft_recommendation` writes via `EventStore.record_verdict` with:
  - `verdict_type="recommended"`
  - `plan_json` = full recommendation object (primary + alternatives + reasoning + urgency)
- Inspect `orbital_ui/src/components/ApproverView.tsx` and confirm it reads:
  - `plan.primary_plan.burns[]` (delta-v + burn_time per burn)
  - `plan.primary_plan.total_dv_mps`
  - `plan.alternative_plans[]`
  - `plan.reasoning`
  - `plan.urgency`
  - If the existing component expects a different field naming, **conform the agent's output schema to the component** rather than refactor the UI

**Acceptance**
- The verdict synthesized by the agent looks identical, in the UI, to a row produced by `/api/dev/synthesize-verdict`

---

## Feature 9 — Scripted demo scenarios

**Goal:** deterministic, repeatable demo. One button per scenario injects a
known conjunction into `conjunction_events` so the agent picks it up.

**Files to create**
- `orbital_agent/scenarios/` — five scenario files:
  - `01_starlink_4521_vs_cosmos_2251.json` — high-Pc, action-required (the worked example from §6)
  - `02_iss_vs_fengyun_debris.json` — high-stakes asset, watch-level Pc
  - `03_stale_tle_false_positive.json` — initial Pc 5e-4 but re-propagation drops it below 1e-6 (dismiss)
  - `04_kp_storm_inflation.json` — Pc straddles threshold; covariance inflation pushes it into action
  - `05_multi_conjunction_split_burn.json` — three upcoming conjunctions for one Starlink; expected outcome is split-burn plan B
- Each file:
  ```json
  {
    "id": "scn-01",
    "name": "STARLINK-4521 vs Cosmos-2251 debris",
    "trigger_button_label": "Scenario 1: High-Pc debris",
    "event": { /* fields matching ConjunctionEventRecord */ },
    "expected_verdict": "recommended",
    "demo_narration": "Two-line script for the presenter"
  }
  ```
- `orbital_api/routes/dev_route.py` — extend with:
  - `GET /api/dev/scenarios` — list scenarios
  - `POST /api/dev/scenarios/{id}/trigger` — inserts the `event` into `conjunction_events` (status `monitoring`, no verdict) so the agent picks it up on next poll
- `orbital_ui/src/components/ScenarioMenu.tsx` — small dropdown in the dashboard header; populates from `/api/dev/scenarios`

**Acceptance**
- Each of the 5 scenarios triggered from the UI produces the expected verdict type on the agent's first pass

---

## Feature 10 — NemoClaw sandbox onboarding (bonus track)

**Goal:** run the OpenClaw daemon inside a NemoClaw-provisioned sandbox so
network egress and filesystem access are policy-gated at the container
boundary. NemoClaw is an alpha sandbox *provisioner* (it builds an OpenShell
container that runs OpenClaw inside it); it is **not** a runtime wrapper
around individual tool calls, and the policy boundary is the container, not
the tool layer.

If NemoClaw onboarding fails or isn't workable at the venue, the agent runs
unsandboxed and the project still satisfies the Edge Track.

**Setup (manual, one-time on the GX10)**
1. `nemoclaw onboard` — runs the wizard that builds an OpenShell container with a Nemotron model preconfigured
2. Replace the wizard's default policy with our custom one (below) and restart the sandbox
3. Inside the sandbox, OpenClaw runs from our `agent.yaml` exactly as in Feature 1

**Files to create**
- `nemoclaw-blueprint/policies/openclaw-sandbox.yaml` — the OpenShell network/filesystem policy:
  - **Network egress**: allow only `localhost` (so the sandboxed OpenClaw can still reach Ollama on `127.0.0.1:11434` and the FastAPI server on `127.0.0.1:8000`); deny all other outbound traffic
  - **Filesystem**: read-only access to `orbital_data/cache/`, read-write to `orbital_data/orbital.db`, read-only to the `orbital_agent/openclaw/` config tree
  - These controls are enforced by OpenShell at the container boundary — they do not allow or deny individual MCP tool calls
- `nemoclaw-blueprint/README.md` — the exact commands to onboard + apply the policy

**What this does and does not do**
- Does: prevents the model (or any process inside the sandbox) from exfiltrating TLE / CDM data to the public internet. Raw orbital state stays in the box.
- Does: gives us the demo line — "the orbital state never leaves the device, enforced at the OS level by NemoClaw."
- Does not: filter individual tool arguments, sanitize outputs, or allowlist specific tools. That's not NemoClaw's job — it's a container sandbox, not a tool firewall.

**Acceptance** (only if pursued)
- OpenClaw running inside the sandbox completes a full investigation against the live MCP server
- From inside the sandbox, `curl https://google.com` is blocked; `curl http://localhost:11434/api/tags` succeeds
- Removing NemoClaw (running OpenClaw directly on the host) requires zero changes to `agent.yaml`, the MCP server, the runner, or any other feature

---

## Cross-cutting: tool-failure resilience

(Per design doc §10 "Tool failures should not crash the agent.")

- Every tool function in `orbital_agent/tools/*` catches its own exceptions
  and returns a structured `{error: "...", fallback: <something usable>}`
  payload the model can react to. FastMCP serializes the dict as the tool
  result and the model decides what to do (often "try the cached path
  instead").
- HTTP calls to the local API use `httpx` with retry (3 attempts, exponential
  backoff), then fall back to cached values where applicable.
- Tool errors are also forwarded to the SSE bus as `{type: "tool_result", content: {name, error}}` so the operator sees the agent recovering live.

---

## Definition of Done (verbatim from design doc §11)

The agent is "working" when, end-to-end without manual intervention:

1. The screener detects a flagged conjunction (already true — screening runs on a 60s loop)
2. The agent picks it up within 30 s
3. Runs the full Investigate loop, streaming ≥ 5 distinct reasoning thoughts to the UI
4. Classifies as dismiss / watch / action based on refined Pc
5. For action: generates ≥ 2 candidate plans, evaluates each, produces a recommendation with both plans + plain-English reasoning
6. Recommendation appears in the Approver View
7. On human approve: simulator applies the plan, conjunction resolves in the 3D viz
8. Full event chain is in memory; `query_memory(asset_id)` returns it

One scripted scenario passing = demo-ready. Three of five = hackathon-grade.
