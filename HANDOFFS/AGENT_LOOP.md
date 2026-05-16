# Orbital — Agent Loop & Scenario Library Handoff

> **You are picking up the agent-side workstream.** Another teammate is
> working in parallel on Feature 4 (the autonomous runner sidecar). Your
> scope is everything *inside one investigation* plus the scenario library
> that drives the demo.

This document is self-contained — you don't need to have read anything else
to start. There are pointers to deeper docs at the end if you want them.

---

## 1. What this project is

**Orbital** is an on-device autonomous agent that does conjunction triage for
satellites in low Earth orbit. It's a 24-hour hackathon project
(Hack-a-Claw x NVIDIA @ UCSC, May 15–16 2026) targeting the Edge Track on
the ASUS Ascent GX10 ("Spark") plus the NemoClaw bonus track.

The one-sentence pitch: **Orbital watches the orbital catalog, detects close
approaches between objects, reasons about which ones matter, and drafts
maneuver recommendations for a human flight director to approve.**

The agent does the analyst's job. Humans approve. Spacecraft execute. This
mirrors how NASA CARA and large commercial operators actually run conjunction
operations — Orbital is automating the highest-effort cognitive layer.

### Key domain terms (so the code reads cleanly)

| Term | Meaning |
|---|---|
| **Conjunction** | A predicted close approach between two orbiting objects |
| **TCA** | Time of Closest Approach — the moment two objects come closest |
| **Miss distance** | Minimum predicted separation in km at TCA |
| **Pc** | Probability of collision (scalar in [0, 1]). Industry action threshold: 1e-4. |
| **TLE** | Two-Line Element set — the standard orbit-state format from CelesTrak |
| **SGP4** | The standard propagator for TLEs |
| **Δv** | Delta-V, change in velocity — a maneuver's "fuel cost", measured in m/s |
| **Kp index** | Geomagnetic activity scale (0–9). Above 5, atmospheric drag predictions get noisy. |
| **NORAD ID** | Integer catalog ID for an orbiting object (e.g., ISS = 25544) |
| **Event** | One conjunction the screening engine flagged. Has a stable ID. |
| **Verdict** | The agent's decision: `dismissed`, `watch`, or `recommended` |

---

## 2. The stack

```
        Ollama daemon (port 11434, OpenAI-compatible HTTP)
                       ▲
                       │ inference: nemotron-3-nano:30b
                       │
        OpenClaw daemon (Node, port 18789 — systemd user service on the Spark)
            ▲                                ▲
            │ kickoff messages                │ MCP over SSE (port 8765)
            │ (`openclaw agent ...`)          │
            │                                 │
   Python sidecar                    orbital_agent/mcp_server.py
   (Feature 4: poll SQLite,          (11 domain tools — our code)
    fire kickoffs)
            │
            ▼
   FastAPI (orbital_api, port 8000) ─── React UI (orbital_ui, port 5173)
            │
            └── SQLite at orbital_data/orbital.db
                (orbital_persist.EventStore — conjunction_events, pc_snapshots, verdicts)
```

**Who owns what:**

- **Ollama**: the LLM inference server. Pre-installed on the Spark.
- **OpenClaw**: a Node-based agent orchestrator. Runs as a systemd user
  service. Owns the reasoning loop, message history, and tool dispatch.
  We don't write OpenClaw code — we configure it (`~/.openclaw/openclaw.json`)
  and connect our MCP server to it.
- **Our Python sidecar (`orbital_agent/`)**: hosts the MCP server,
  renders kickoff prompts, and (Feature 4) will poll the DB autonomously.
- **`orbital_engine/`, `orbital_data/`, `orbital_persist/`, `orbital_api/`,
  `orbital_ui/`**: pre-existing pieces of the project. The screening
  engine, SGP4 propagation, Pc computation, FastAPI routes, and React
  dashboard. You will rarely touch these.

---

## 3. What's already built (Features 1, 2, 3)

If you run `python scripts/check_ready.py` on the Spark, you should get
all PASS. If not, see §8.

### Feature 1 — OpenClaw + Ollama + Python scaffolding

Files:
- `orbital_agent/__init__.py` — package marker
- `orbital_agent/config.py` — env-driven `AgentConfig` (model name, OpenClaw URL, DB path, …)
- `orbital_agent/gateway.py` — health checks against the OpenClaw daemon (basic reachability)
- `orbital_agent/__main__.py` — CLI: `--smoke`, `--investigate <event_id>`, `--run`
- `orbital_agent/openclaw/workspace/SOUL.md` — the agent's identity / role / output protocol
- `orbital_agent/openclaw/README.md` — OpenClaw config notes
- `orbital_agent/openclaw/FOLLOWUPS.md` — record of the OpenClaw tool-surface narrowing
- `scripts/check_ready.py` — 14-check readiness verifier

On the Spark, OpenClaw is configured to:
- Run on `ws://127.0.0.1:18789` (gateway)
- Use model `ollama/nemotron-3-nano:30b`
- Mount an agent called `orbital` whose workspace is
  `~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace/`
- Tool surface profile: `minimal`, with our 11 MCP tools added via
  `agents.list[*].tools.alsoAllow` (prefixed `orbital__*`)

### Feature 2 — MCP server exposing 11 domain tools

Files:
- `orbital_agent/mcp_server.py` — FastMCP entrypoint over SSE on port 8765
- `orbital_agent/tools/data.py` — 4 fetch tools
- `orbital_agent/tools/memory.py` — `query_memory`, `write_memory`
- `orbital_agent/tools/analysis.py` — `re_propagate`, `compute_collision_probability`, `simulate_maneuver`, `evaluate_plan`
- `orbital_agent/tools/output.py` — `draft_recommendation`
- `orbital_agent/tools/_pydantic_models.py` — Pydantic models (used internally only)
- `orbital_engine/maneuver.py` — Two-body Kepler propagation + impulsive Δv (used by simulate_maneuver / evaluate_plan)
- `orbital_data/cache/asset_profiles.json` — seed data (is_maneuverable, fuel, etc.) per NORAD

The 11 tools, as the model sees them (OpenClaw prefixes them with `orbital__`):

| Tool | Purpose |
|---|---|
| `get_flagged_conjunctions(min_pc, asset_norad_id)` | Live screener output, filtered |
| `get_object_metadata(norad_id)` | SATCAT + operator profile (is_maneuverable, fuel) |
| `get_space_weather()` | NOAA SWPC snapshot (Kp, X-ray, storm level) |
| `get_conjunctions_for_asset(norad_id, limit)` | Upcoming + recent events for one asset |
| `query_memory(norad_id, event_id, limit)` | Prior events + verdicts |
| `write_memory(event_id, verdict_type, reasoning, plan)` | Persist dismiss/watch verdict |
| `re_propagate(norad_id, at_iso)` | Fresh SGP4 from latest TLE |
| `compute_collision_probability(norad_id_a, norad_id_b, at_iso, kp_index, covariance_inflation)` | Pc + band (noise/watch/action). Propagates internally. |
| `simulate_maneuver(norad_id, dv_mps, direction, burn_time_iso, look_ahead_hours)` | Apply impulsive Δv, return trajectory samples |
| `evaluate_plan(asset_norad_id, burn_dvs_mps, burn_directions, burn_times_iso, miss_threshold_km)` | Score a multi-burn plan against the asset's upcoming events |
| `draft_recommendation(event_id, recommendation_json)` | Persist a "recommended" verdict to the UI Approver queue |

**Important design rule for any new tool you might add:** Nemotron Nano on
Ollama **reliably handles flat primitive args and arrays of primitives** but
struggles to construct nested objects in tool arguments. Stick to ints,
floats, strs, lists of primitives, or — for the deeply-nested case
(`draft_recommendation`) — JSON strings that the tool parses internally.
Don't pass typed Pydantic objects as MCP arg shapes.

### Feature 3 — Kickoff harness

Files:
- `orbital_agent/prompts/investigate_kickoff.txt` — the per-event user-turn template
- `orbital_agent/kickoff.py` — `build_kickoff(event)` renders the template; `send_kickoff_for_event(event_id)` shells out to `openclaw agent --agent orbital --thinking high --json --session-id <uuid>` and parses the session JSONL for tool calls + verdict
- `scripts/insert_demo_scenario.py` — inserts one hard-coded scenario
- `scripts/run_demo_investigation.py` — Feature 3 acceptance harness

**The agent loop today** (when you run `python -m orbital_agent --investigate <event_id>`):

1. Python looks up the event in SQLite
2. Renders the kickoff template
3. Calls `openclaw agent --agent orbital --thinking high --json --session-id <new-uuid> --message <kickoff>`
4. OpenClaw daemon runs the reasoning loop:
   a. Loads SOUL.md and other workspace files into the system prompt
   b. Sends prompt + tool list to Nemotron via Ollama
   c. Nemotron returns either text or a tool call
   d. If tool call: OpenClaw routes it to our MCP server, gets the result, appends to conversation, goes back to (b)
   e. If terminal text: the loop ends
5. OpenClaw writes the full session to `~/.openclaw/agents/orbital/sessions/<session_id>.jsonl`
6. The Python harness parses that JSONL for tool calls + reasoning events
7. Final verdict shows up in the `verdicts` SQLite table (assuming the model called `write_memory` or `draft_recommendation`)

**What a real investigation looked like** (231 seconds, 6 tool calls,
"dismissed" verdict):

```
1. orbital__query_memory(norad_id=44714)         # prior events for STARLINK-1008
2. orbital__get_space_weather()                  # Kp=2.67, quiet
3. orbital__get_object_metadata(norad_id=44714)  # asset info, fuel budget
4. orbital__compute_collision_probability(...)   # refined Pc with fresh propagation
5. orbital__write_memory(...)                    # initial verdict (had a schema issue)
6. orbital__write_memory(...)                    # retried, succeeded
```

---

## 4. Your scope (what needs to be done)

You have two tracks running together: **agent loop improvements** and
**Feature 9 (scenario library)**. Both touch the agent's behavior, so it
makes sense to own both.

### Track A — Agent loop improvements

Things we observed in the first real investigation that are worth fixing:

**A.1 — Redundant `write_memory` calls.** The model called `write_memory`
twice (the first attempt apparently had an arg issue, second succeeded).
Look at the session JSONL for the failed investigation we ran
(`~/.openclaw/agents/orbital/sessions/<id>.jsonl`) to see exactly what
went wrong. Likely fixes:
- Tighter docstring on `write_memory` (in `orbital_agent/tools/memory.py`).
- Add explicit examples in SOUL.md.

**A.2 — Inefficient reasoning paths.** With `--thinking high`, the model
produces ~2,000 reasoning tokens before each tool call, taking ~45-60s per
turn. A real investigation took 231s for 6 tool calls. We can probably
get this to 90s by:
- Encouraging fewer redundant tool calls (we already added "Efficient tool
  use" to SOUL.md, but the model could still benefit from more guidance).
- Testing `--thinking medium` — edit `orbital_agent/kickoff.py`, change the
  default from `"high"` to `"medium"`. Measure the delta.
- Looking at whether Nemotron can do parallel tool calls (it has a
  `stopReason: toolUse` per turn — implies one tool per turn currently).
  If it can be parallelized, that'd be a big win.

**A.3 — Tool-call schema confusion.** Even though we flattened the
signatures, the model occasionally still mis-shapes arguments. Each retry
costs ~60s. Watch for repeated validation errors in the session JSONL and
tighten tool docstrings accordingly.

**A.4 — Verdict-decision discipline.** In our 231s run, the model called
`write_memory` (a "dismiss" verdict) when it could have called
`draft_recommendation` (action-required). For the demo we want
action-required scenarios to deterministically reach `draft_recommendation`.
Two angles:
- Better SOUL.md guidance on when to use each verdict tool.
- Better scenarios (track B) so the model's reasoning lands where we want.

**A.5 — Soft accuracy bound on the maneuver math.** Our two-body Kepler
propagator (`orbital_engine/maneuver.py`) diverges from SGP4 by ~40 km over
90 minutes (no J2, no drag). The agent's verdict math is approximate.
This is acceptable for the demo but worth knowing. Don't try to "fix" this
during the hackathon — that's a multi-day J2-propagator project.

**Where you'll be editing for Track A:**
- `orbital_agent/openclaw/workspace/SOUL.md` — agent identity, rules,
  decision criteria. Biggest lever.
- `orbital_agent/prompts/investigate_kickoff.txt` — the per-event
  user-turn message.
- `orbital_agent/tools/*.py` — tool docstrings (FastMCP exposes them to
  the model as tool descriptions). Bad descriptions cause bad tool use.
- `orbital_agent/kickoff.py` — the `thinking` level passed to
  `openclaw agent`.

**How to test changes:** kill the MCP server (`pkill -f orbital_agent.mcp_server`),
restart it (`python -m orbital_agent.mcp_server --transport sse --port 8765 &`),
then run `python scripts/run_demo_investigation.py`. The runner reports
duration, tool count, and verdict. Aim to (eventually) drive a single
investigation to <120s with the correct verdict type.

### Track B — Feature 9: Scenario library

**Why this matters:** the live demo needs deterministic, repeatable
scenarios. We can't depend on the real screener finding a juicy conjunction
in the next 3 minutes. We pre-script 5 scenarios, hot-key trigger them,
and the agent reasons through each one on demand.

**Critical lesson we just learned the hard way:** if you just insert a row
into `conjunction_events` with `initial_pc=3.2e-4` as a number, the model
won't believe it. The first thing the model does is call
`compute_collision_probability`, which propagates the real TLEs to the real
TCA and gets a fresh Pc. If the propagated geometry doesn't actually have
the objects near each other, the refined Pc will be tiny and the model
correctly dismisses it as a false positive.

**So scenarios need real geometry, not just metadata claims.** For each
scenario you want to produce a non-trivial verdict (watch / action), you
need to find a TCA where the propagated positions of the chosen objects
are genuinely close.

**Two ways to find real geometry:**

1. **Run the real screener.** Use `orbital_engine.screening.screen_conjunctions`
   over the next 72 hours on the cached TLE catalog, filter by miss
   distance < 1 km, pick events that have the dramatic asset pairings we
   want (Starlink vs Cosmos debris, ISS vs Fengyun, etc.). Then encode
   those into scenario files.
2. **Synthesize TLEs.** Construct a TLE for a hypothetical object whose
   propagated position at TCA is exactly N meters from a real object. More
   work, more control.

Option 1 is the lower-effort path. Likely a single script
(`scripts/find_real_conjunctions.py`) that runs the screener, prints
candidates, and you pick 5 that fit the narrative.

**Five scenarios PLAN.md calls for (your starting list — adjust as needed):**

| ID | Name | Expected verdict | Demo narrative |
|---|---|---|---|
| 01 | STARLINK-1008 vs Cosmos-2251 debris | `recommended` (high Pc, action-required) | The headline scenario from design doc §6 |
| 02 | ISS vs Fengyun-1C debris | `watch` (high-stakes asset, watch-level Pc) | "What does the agent do when the ISS itself is involved?" |
| 03 | Stale TLE false positive | `dismissed` (initial Pc 5e-4 → refined < 1e-6) | Shows the agent's skepticism in action |
| 04 | Kp storm covariance inflation | `recommended` (Pc straddles threshold; Kp>5 pushes it over) | Shows the space-weather reasoning |
| 05 | Multi-conjunction split-burn | `recommended` (3 events, split-burn plan resolves all) | Shows multi-event planning |

For each scenario, define both the conjunction data AND the expected
outcome:

```json
{
  "id": "scn-01",
  "name": "STARLINK-1008 vs Cosmos-2251 debris",
  "trigger_button_label": "S1: High-Pc debris",
  "event": {
    "obj1_norad_id": 44714,
    "obj1_name": "STARLINK-1008",
    "obj2_norad_id": 33757,
    "obj2_name": "COSMOS 2251 DEB",
    "tca_iso": "2026-05-16T21:27:48Z",
    "miss_distance_km": 0.712,
    "initial_pc": 3.2e-4,
    "relative_velocity_km_s": 14.8
  },
  "expected_outcome": {
    "verdict_type": "recommended",
    "must_call_tools": [
      "compute_collision_probability",
      "draft_recommendation"
    ],
    "min_tool_calls": 4,
    "max_duration_seconds": 600,
    "min_text_events": 5
  },
  "demo_narration": "Starlink-1008 is on a collision course with debris from the 2009 Iridium-Cosmos collision. The agent investigates, finds the Pc still above 1e-4 after refinement, generates a split-burn plan."
}
```

**Files to create:**
- `orbital_agent/scenarios/01_starlink_vs_cosmos.json` through `05_multi_conjunction.json`
- `scripts/find_real_conjunctions.py` — helper script that prints candidate real conjunctions for you to choose from
- `scripts/insert_scenario.py` — replaces `scripts/insert_demo_scenario.py`; reads any scenario JSON file and inserts it
- `scripts/run_scenario_suite.py` — runs ALL scenarios sequentially, validates each against its `expected_outcome`, prints a final pass/fail per scenario plus a summary
- (Later, depends on UI work) `orbital_api/routes/dev_route.py` — extend with `GET /api/dev/scenarios` and `POST /api/dev/scenarios/{id}/trigger`
- (Later) `orbital_ui/src/components/ScenarioMenu.tsx` — UI dropdown

**Validation rules for the suite runner:**

DO check:
- Did the verdict type match `expected_outcome.verdict_type`?
- Did `must_call_tools` all appear in the tool-call list?
- Was tool-call count ≥ `min_tool_calls`?
- Was duration ≤ `max_duration_seconds`?
- Were there ≥ `min_text_events` reasoning emissions?

DO NOT check:
- Exact wording of the final reply (LLMs are non-deterministic)
- Exact Δv values in recommended plans (depends on the model's reasoning)
- The order of tool calls (model may shuffle)

**Output of `scripts/run_scenario_suite.py` should look like:**

```
=========================================================
Scenario suite
=========================================================
[PASS] scn-01 STARLINK-1008 vs Cosmos-2251     (verdict=recommended, 5 tools, 187s)
[PASS] scn-02 ISS vs Fengyun-1C debris         (verdict=watch, 4 tools, 142s)
[FAIL] scn-03 Stale TLE false positive         (expected dismissed, got watch)
[PASS] scn-04 Kp storm inflation               (verdict=recommended, 6 tools, 198s)
[PASS] scn-05 Multi-conjunction split-burn     (verdict=recommended, 7 tools, 256s)

4/5 scenarios PASS  (28% of demo coverage at risk: scn-03)
```

---

## 5. What you should NOT touch (Feature 4's scope)

The teammate working on Feature 4 owns:
- `orbital_agent/runner.py` (will be created — autonomous polling loop)
- `orbital_agent/queue.py` (will be created — next_pending_event helper)
- `orbital_agent/heartbeat.py` (will be created — 30s idle heartbeats)
- `orbital_agent/__main__.py` (the `--run` mode; you can read this file
  but don't modify the `--run` path)

If you need something from the runner side (e.g., a hook to call after each
scenario), coordinate before writing it.

You CAN touch (these affect both tracks but you're more likely to need
them):
- `orbital_agent/kickoff.py` — agreeing on its interface helps both
- `orbital_agent/openclaw/workspace/SOUL.md` — agent identity. Coordinate
  with the Feature 4 person before big rewrites.

---

## 6. Setup on the Spark

Everything below assumes you're in `~/Orbital_nvidia_asus/` with the venv
activated:

```bash
cd ~/Orbital_nvidia_asus
source .venv/bin/activate
```

### One-time

```bash
# Confirm the stack is up
python scripts/check_ready.py
# All 14 checks should PASS. If not, see error messages — usually one of:
#   - MCP server died: pkill -f orbital_agent.mcp_server ; python -m orbital_agent.mcp_server --transport sse --port 8765 &
#   - FastAPI not running: uvicorn orbital_api.main:app --host 127.0.0.1 --port 8000 &
#   - OpenClaw config drift: openclaw config validate
```

### Daily iteration loop

```bash
# 1. Make a change (SOUL.md, a tool docstring, etc.)
vim orbital_agent/openclaw/workspace/SOUL.md

# 2. If you changed a tool, restart the MCP server so the new schemas
#    propagate (workspace .md files are re-read per session, but tool
#    schemas are cached at MCP-server startup).
pkill -f orbital_agent.mcp_server
sleep 1
python -m orbital_agent.mcp_server --transport sse --port 8765 &
sleep 2

# 3. Run one investigation and look at the result
python scripts/run_demo_investigation.py
# Outputs: PASS/FAIL per criterion, duration, tool count, verdict.

# 4. Inspect the session JSONL for what actually happened
ls -t ~/.openclaw/agents/orbital/sessions/*.jsonl | head -1 | xargs less
# Look for: "thinking" blocks (the model's reasoning), "toolCall" entries,
# "toolResult" entries, validation errors, retries.

# 5. Iterate
```

### Scenario suite testing

Once you've built scenarios + the suite runner:

```bash
# Run all 5 scenarios and report
python scripts/run_scenario_suite.py

# Run just one scenario
python scripts/insert_scenario.py orbital_agent/scenarios/01_starlink_vs_cosmos.json
python -m orbital_agent --investigate <event_id_printed_by_insert>
```

---

## 7. What "done" looks like

For Track A (agent loop improvements):
- A single investigation runs in <120s with `--thinking medium`, or <180s
  with `--thinking high`
- Tool-call validation errors are rare (≤1 retry per investigation typical)
- The model reliably picks the right verdict tool: `write_memory` for
  dismiss/watch, `draft_recommendation` for action-required
- The 231s run from earlier becomes 90-120s

For Track B (scenario library):
- 5 scenarios on disk in `orbital_agent/scenarios/`
- A `scripts/run_scenario_suite.py` that runs all 5 and prints a summary
- At least 4/5 PASS their `expected_outcome` on a fresh run
- (Stretch) `/api/dev/scenarios` endpoint + `ScenarioMenu` UI component
  for hot-key demo triggering

---

## 8. Where to read more

| Doc | What's in it |
|---|---|
| `PLAN.md` (repo root) | The full 10-feature build plan. Your scope is Track-A scattered improvements + Feature 9. Feature 4 (runner) is the other track. |
| `orbital_agent/openclaw/FOLLOWUPS.md` | History of the OpenClaw tool-surface narrowing (already applied). Useful as background on how the per-agent config works. |
| `orbital_agent/openclaw/README.md` | OpenClaw-specific notes (where SOUL.md lives, etc.) |
| `OrbitalAgent.pdf` (repo root) | Original design document. Section 5 has the model-facing system prompt. Section 6 has a worked example. Section 7 has the memory schema. |
| `OrbitalProjectOverview.pdf` (repo root) | High-level project overview |
| `README.md` (repo root) | How to run the API + UI |

---

## 9. Quick reference: useful commands

```bash
# Restart the whole agent stack from scratch
pkill -f orbital_agent.mcp_server
pkill -f "uvicorn orbital_api.main"
uvicorn orbital_api.main:app --host 127.0.0.1 --port 8000 &
sleep 2
python -m orbital_agent.mcp_server --transport sse --port 8765 &
sleep 2
python scripts/check_ready.py

# Tail the agent's reasoning live during an investigation
ls -t ~/.openclaw/agents/orbital/sessions/*.jsonl | head -1 | xargs tail -f

# See the verdict written
sqlite3 orbital_data/orbital.db "SELECT verdict_id, event_id, verdict_type, issued_at FROM verdicts ORDER BY issued_at DESC LIMIT 5;"

# See the plan JSON for the latest recommendation
sqlite3 orbital_data/orbital.db "SELECT plan_json FROM verdicts WHERE verdict_type='recommended' ORDER BY issued_at DESC LIMIT 1;"

# Reset a stuck scenario row
sqlite3 orbital_data/orbital.db "DELETE FROM verdicts WHERE event_id='<event_id>'; DELETE FROM pc_snapshots WHERE event_id='<event_id>'; DELETE FROM conjunction_events WHERE event_id='<event_id>';"

# List the tools OpenClaw is actually exposing to the agent right now
openclaw agent --agent orbital --json --message "ack" 2>/dev/null \
  | python3 -c "import json,sys; sp=json.load(sys.stdin)['result']['meta']['systemPromptReport']; print(*sorted(t['name'] for t in sp['tools']['entries']), sep='\n')"
```

---

## 10. Slack / coordination

- Daily standup: check in with the Feature 4 person on whether either of
  you has touched `kickoff.py` or `SOUL.md`. Those are the main shared files.
- If you find a bug in shared infrastructure (`orbital_agent/tools/*.py`
  for example), fix it on a branch and ping the other person before
  merging — they may be calling those tools from the runner.
- If a scenario insertion ends up changing the DB in a way that breaks
  Feature 4's polling, coordinate. The runner is meant to pick up monitoring
  events — your scenarios should land as `status='monitoring'` with no
  verdict yet, which is also what real screening writes. They should be
  compatible by construction.

Good luck. Most of the heavy lifting is done — the agent loop works
end-to-end. Your job is to make it work *well*.
