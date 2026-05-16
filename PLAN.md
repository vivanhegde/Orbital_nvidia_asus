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
| `simulate_maneuver`, `evaluate_plan` | **Not built** | Mock implementations are sufficient for the demo. |

**Locked decisions** (from design doc §10.5, settled here so no day-0 debate):

| Decision | Value |
|---|---|
| Inference model | Nemotron-3-Nano-30B-A3B-FP8 |
| Inference server | Ollama (OpenAI-compatible HTTP endpoint at `localhost:11434/v1`) |
| Agent orchestrator | **OpenClaw** — owns the reasoning loop, message history, and tool dispatch. Points at Ollama as its model backend. |
| Tool-call format | Whatever OpenClaw uses natively (verified day-0). Tool *functions* are framework-agnostic; only the schema-emission layer is OpenClaw-specific. |
| Streaming format | Server-Sent Events (SSE) |
| Memory backend | Existing SQLite via `orbital_persist.EventStore` |
| Event queue | SQLite polling on `conjunction_events` (no in-memory queue, no Redis) |
| Agent process | Separate Python process alongside `uvicorn`, sharing the same SQLite DB |

**Known risk:** the design doc itself flags OpenClaw as the single biggest day-0 risk ("we have not verified these frameworks are mature enough to use"). Feature 1 therefore frontloads an OpenClaw smoke test before any orbital-specific work depends on it.

The design doc's §7 claim that memory is "a single SQLite table" is wrong — the
real schema is three tables (already built and indexed). No migration is
required. `query_memory` and `write_memory` map onto `EventStore` methods as
specified below.

---

## Feature 1 — Agent runtime: package layout + OpenClaw + Ollama wiring

**Goal:** an `orbital_agent/` Python package that runs as its own process,
hosts an OpenClaw agent pointed at a local Ollama-served Nemotron, and can
complete a single tool-using turn end-to-end.

**Files to create**
- `orbital_agent/__init__.py`
- `orbital_agent/config.py` — env-driven config (`ORBITAL_MODEL`, `OLLAMA_BASE_URL`, `DB_PATH`, `API_BASE_URL`, `HEARTBEAT_SECONDS`, `LOG_LEVEL`, `OPENCLAW_*` overrides)
- `orbital_agent/openclaw_client.py` — thin shim that:
  - Instantiates an OpenClaw agent
  - Configures its model backend to point at Ollama's OpenAI-compatible endpoint (`http://localhost:11434/v1`, model `nemotron3-nano:30b-a3b-fp8`)
  - Exposes one entrypoint `run_turn(messages, tools) -> AgentTurnResult` that wraps OpenClaw's run loop and yields streamed events (text chunks + tool-call events) for Feature 5 to forward over SSE
- `orbital_agent/__main__.py` — entrypoint: `python -m orbital_agent`, supports `--selftest` and `--smoke-openclaw`
- `orbital_agent/requirements.txt` — `openclaw`, `httpx`, `pydantic`, `sse-starlette`

**Day-0 OpenClaw smoke test (do this first, before Features 2–9 depend on it)**
- `python -m orbital_agent --smoke-openclaw` does exactly three things:
  1. Boots OpenClaw with one trivial stub tool `echo(text: str) -> str`
  2. Sends a one-message conversation that should provoke a tool call
  3. Prints the streamed events and the final assistant message
- If this passes, the rest of the plan proceeds unchanged. If it fails, the day-0 task is to debug OpenClaw — every other feature is blocked until this works, because Features 2–4 all build on its tool-registration and streaming surface.

**Acceptance**
- `python -m orbital_agent --selftest` runs the smoke test plus one round-trip with a real tool (`get_space_weather`) and exits 0
- Environment variables override every default cleanly
- OpenClaw's streamed events are surfaced as an iterator that downstream code (Feature 5) can attach to

**Out of scope:** prompt logic (Feature 3), real tool implementations (Feature 2), SSE endpoint (Feature 5).

---

## Feature 2 — Tool layer (the 12 agent tools)

**Goal:** every `tool_name(...)` the agent can call resolves to one typed,
documented Python function that OpenClaw registers directly. Two of the twelve
(`simulate_maneuver`, `evaluate_plan`) are new implementations built on top of
the existing engine primitives — real math, simplified modeling. No separate
schema file; OpenClaw introspects signatures and docstrings.

**Files to create**
- `orbital_agent/tools/__init__.py` — single source of truth: imports every tool function and exposes `TOOLS: list[Callable]` for OpenClaw to register
- `orbital_agent/tools/data.py` — `get_flagged_conjunctions`, `get_object_metadata`, `get_space_weather`, `get_conjunctions_for_asset`
- `orbital_agent/tools/memory.py` — `query_memory`, `write_memory`
- `orbital_agent/tools/analysis.py` — `re_propagate`, `compute_collision_probability`, `simulate_maneuver`, `evaluate_plan`
- `orbital_agent/tools/output.py` — `draft_recommendation`, `stream_thought`

**Schema generation:** OpenClaw derives the tool schema from each function's Python type hints + docstring (standard modern-agent-framework behavior). We do **not** maintain a separate `schemas.py` JSON file. Every tool function must therefore have:
- Fully typed parameters (using `Pydantic` models for nested arguments like `delta_v_vector` and `burn_sequence`)
- A one-line docstring that becomes the tool description the model sees
- A typed return value (so OpenClaw can serialize results back into the message stream)

Day 0, after the Feature 1 smoke test confirms how OpenClaw introspects signatures, verify this assumption — if OpenClaw needs an explicit `@tool` decorator or a Pydantic-model-per-tool, add it here rather than reinventing schema emission.

**Mapping (authoritative)**

| Tool | Implementation | Status |
|---|---|---|
| `get_flagged_conjunctions(since, min_pc, asset_filter)` | HTTP GET `/api/conjunctions/flagged`; filter client-side | Real |
| `get_object_metadata(object_id)` | `orbital_data.store.get_satcat_record(norad_id)` + augment with `is_maneuverable`/`fuel_remaining_mps` derived from a small JSON table seeded in `orbital_data/cache/asset_profiles.json` (only entries for the demo assets need to exist) | Real + tiny seed file |
| `get_space_weather()` | HTTP GET `/api/space-weather` | Real |
| `get_conjunctions_for_asset(asset_id, horizon_hours)` | HTTP GET `/api/memory/asset/{norad_id}` filtered by TCA window | Real |
| `query_memory(asset_id, conjunction_id, limit)` | `EventStore.query_events_for_asset` + `get_verdict` joins | Real |
| `write_memory(record)` | `EventStore.record_verdict(...)` | Real |
| `re_propagate(object_id, use_latest_tle)` | `orbital_data.store.get_tles(...)` then `orbital_engine.propagation.propagate(tle, now)` | Real |
| `compute_collision_probability(obj1_state, obj2_state, covariance_inflation)` | `orbital_engine.pc.compute_pc(...)` — covariance inflation factor comes from Feature 4's Kp helper | Real |
| `simulate_maneuver(asset_id, delta_v_vector, burn_time)` | Add ΔV vector to the propagated velocity at `burn_time`, re-propagate the modified state forward using real SGP4 (`orbital_engine.propagation`), return the new state series. Simplification: state carried in-memory, no TLE refit | New (built in Feature 7's `orbital_engine/maneuver.py`) |
| `evaluate_plan(asset_id, burn_sequence)` | Iterate `simulate_maneuver` over the burn sequence, then re-run `orbital_engine.screening.screen_conjunctions` against the modified trajectory; return `{resolved_event_ids, new_event_ids, total_dv_mps, fuel_remaining_mps, residual_max_pc}`. Real screening on the simulated trajectory | New (Feature 7) |
| `draft_recommendation(asset_id, recommended_plan, alternative_plans, reasoning, urgency)` | `EventStore.record_verdict(event_id, verdict_type="recommended", reasoning, plan=...)` where `plan` is the full JSON spec (primary + alternatives) | Real |
| `stream_thought(text)` | Push to in-process broadcaster (Feature 5) | New transport |

**Acceptance**
- `python -m orbital_agent.tools --list` prints every registered tool with its OpenClaw-derived schema (proves introspection works)
- `python -m orbital_agent.tools --dry-run get_flagged_conjunctions` calls the live API and prints results
- `simulate_maneuver` / `evaluate_plan` run end-to-end on a real flagged event and return plausible numbers

---

## Feature 3 — Reasoning loop + prompts (OpenClaw-driven)

**Goal:** OpenClaw runs the reasoning loop; this feature provides the prompts,
the mode wrapper, and the outer runner. We do **not** hand-roll the
call/dispatch/append cycle — OpenClaw owns that.

**Files to create**
- `orbital_agent/prompts/system.txt` — system prompt (verbatim from design doc §5: "You are Orbital, an autonomous orbital safety analyst…")
- `orbital_agent/prompts/investigate_kickoff.txt` — user-turn template (per design doc §5.5):
  ```
  A new conjunction has been flagged.
  Event ID: {event_id}
  Objects: {obj1_name} (NORAD {obj1_id}) vs {obj2_name} (NORAD {obj2_id})
  TCA: {tca}
  Initial miss distance: {miss_km} km
  Initial Pc: {initial_pc}
  Begin your investigation following the protocol. Stream your thoughts as you go.
  ```
- `orbital_agent/loop.py` — `run_investigation(event_id) -> VerdictRecord`:
  1. Build the kickoff message from the event row
  2. Hand `(system_prompt, kickoff_message, TOOLS)` to `openclaw_client.run_turn(...)` and let it run until completion (OpenClaw introspects schemas from the tool functions themselves)
  3. Stream every event OpenClaw emits — text chunks, tool-call announcements, tool-result confirmations — out through Feature 5's bus so the UI sees the agent think in real time
  4. Configure OpenClaw with a hard cap of 25 tool calls per investigation (or the equivalent OpenClaw setting) to bound runaway loops
  5. After the run completes, locate the verdict row OpenClaw caused via `draft_recommendation` and return it
- `orbital_agent/modes.py` — `IdleMonitor`, `Investigate`, `Plan` are thin wrappers around `run_investigation`. The model decides internally when to escalate from Investigate to Plan based on the Pc thresholds in the system prompt; we don't enforce the transition outside the model. `IdleMonitor` is the wait-state between investigations.
- `orbital_agent/runner.py` — outer driver: poll the queue (Feature 4), pick the next event, invoke `run_investigation`, emit heartbeats between events

**Design notes**
- The model decides when to call `draft_recommendation` — OpenClaw passes it through to the registered tool, which validates the JSON and writes to `verdicts` via `EventStore.record_verdict`. Verdict type ∈ `dismissed | watch | recommended`.
- If OpenClaw exposes per-step hooks (pre-tool-call, post-tool-result), use them to fan out into the SSE bus. If it only exposes a streaming-iterator API, wrap that with an async producer.
- Recommendation JSON schema (what `draft_recommendation` validates before persisting; from design doc §5.5):
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
- Worked example from design doc §6 (STARLINK-4521 vs Cosmos-2251 debris, Pc 3.2e-4) runs end-to-end against the real tool layer and produces a verdict row with both a primary plan and at least one alternative
- ≥ 5 distinct `stream_thought` calls per investigation (matches Definition of Done)
- Investigation finishes within 60 s on the target hardware (loosely; not a hard requirement)

---

## Feature 4 — Event queue, heartbeat, covariance inflation helper

**Goal:** the agent pulls work without anyone pushing to it, and stays visible
on the UI between events.

**Files to create**
- `orbital_agent/queue.py`
  - `next_pending_event(store: EventStore) -> ConjunctionEventRecord | None` — SQL: events with `status='monitoring'` that have **no verdict** yet (left join `verdicts`), ordered by initial Pc desc, then `first_detected_at` asc
  - `mark_in_progress(event_id)` / `mark_done(event_id)` — uses an in-memory set (one agent process, synchronous loop, no race)
- `orbital_agent/heartbeat.py` — every 30 s while idle, emit one `stream_thought`: `"Monitoring {n_objects} objects, {n_watch} in elevated-risk watch, no new flags in last 30s."` Stats come from `/api/catalog-summary` and `/api/memory/recent?status=monitoring`
- `orbital_agent/space_weather.py` — `covariance_inflation_from_kp(kp: float) -> float`:
  - `kp < 5.0` → 1.0
  - `5.0 ≤ kp < 6.0` → 1.18
  - `kp ≥ 6.0` → 1.4
  - This is exposed to the agent indirectly: the system prompt tells the model to inflate covariance during elevated Kp; `compute_collision_probability` accepts the factor as an argument and the model passes it. We provide the helper so the *tool* can default it if the model omits it.

**Acceptance**
- Runner sits in `IDLE_MONITOR`, emits one heartbeat every 30 s
- When a row appears in `conjunction_events` with no verdict, the runner picks it up within one poll interval (default 5 s; configurable) and transitions to `INVESTIGATE`
- After completion, returns to `IDLE_MONITOR`

---

## Feature 5 — Agent → UI transport (SSE)

**Goal:** real reasoning shows up in `AgentReasoningStream.tsx` instead of the
hardcoded `AGENT_LOGS` mock.

**Backend**
- `orbital_api/agent_bus.py` — in-process pub/sub. Class `AgentBus` with `publish(event: dict)` and `subscribe() -> AsyncIterator[dict]`. Single instance, registered in `main.py`'s lifespan
- `orbital_api/routes/agent_route.py`
  - `GET /api/agent/stream` — SSE endpoint, yields `data: <json>\n\n` for each event from `AgentBus.subscribe()`. Uses `sse-starlette` for backpressure
  - `POST /api/agent/event` — internal endpoint the agent process POSTs to. Body: `{type, content, related_event_id?, timestamp}`. Adds to bus, returns 204
- Wire route in `orbital_api/main.py`

**Agent side**
- `orbital_agent/transport.py` — `emit(event_type, content, related_event_id=None)` — HTTP POST to `/api/agent/event`. Used by `stream_thought` and by mode transitions (`investigate_start`, `verdict_drafted`, `heartbeat`)

**Event shape**
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
- `orbital_ui/src/components/AgentReasoningStream.tsx` — replace hardcoded `AGENT_LOGS` with the live stream; keep the same visual treatment (auto-scroll, typewriter-style for new lines)
- Token-by-token streaming: if Ollama streams chunks for an assistant message, the agent forwards them one event per chunk so the UI renders progressively (per design doc §8)

**Acceptance**
- Open the dashboard with the agent running → the reasoning panel shows live, scrolling output (heartbeats when idle, full investigation flow when an event triggers)
- Refreshing the page reconnects cleanly; missed events are not replayed (acceptable for demo)

---

## Feature 6 — Memory tools wired to existing EventStore

**Goal:** `query_memory` and `write_memory` map cleanly onto the existing
3-table schema without inventing a parallel store.

**Implementation**
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

## Feature 10 — NemoClaw sandbox wrapping (bonus track)

**Goal:** wrap the agent process in NemoClaw so tool calls go through a policy
boundary. Treat as optional — if NemoClaw is not workable, the agent runs
unwrapped and the project still satisfies the Edge Track.

**Implementation**
- `orbital_agent/nemoclaw_wrapper.py` — minimal shim that hosts the same `TOOLS` registry behind NemoClaw's invocation API. The policy file declares:
  - Allow: all 12 agent tools
  - Deny: outbound HTTP to anything other than `localhost`
  - Sanitization: outbound `stream_thought` / `draft_recommendation` payloads stripped of raw TLE lines
- `nemoclaw_policy.yaml` — policy spec at repo root
- Boot mode chosen by env var `ORBITAL_USE_NEMOCLAW=1`

**Acceptance** (only if pursued)
- Agent reasoning works identically wrapped vs unwrapped
- Removing the wrapper at runtime requires no code changes on the API/UI side

---

## Cross-cutting: tool-failure resilience

(Per design doc §10 "Tool failures should not crash the agent.")

- Every tool wrapper in `orbital_agent/tools/*` is decorated with a `@safe_tool`
  decorator that catches exceptions, emits a `stream_thought` like
  `"re_propagate failed: <reason>; falling back to cached state"`, and returns
  a structured `{error: "...", fallback: ...}` payload the model can react to
- HTTP calls to the local API use `httpx` with retry (3 attempts, exponential
  backoff), then fall back to cached values where applicable

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
