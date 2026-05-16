# OpenClaw cleanup — Feature 1 follow-ups

Two cleanup tasks that surfaced during Feature 1 verification. They must be
finished **before Feature 3** (the reasoning loop), but they don't block
Feature 2 (the MCP server with 11 domain tools). Someone else is doing
Feature 2 in parallel — this doc is for the person on the cleanup track.

**Estimated effort:** 30–90 minutes if everything goes smoothly. Plus one
re-verification pass after Feature 2 lands.

---

## 1. Project context (one minute)

Orbital is an on-device autonomous agent for conjunction triage in low Earth
orbit. It runs on the ASUS Ascent GX10 ("Spark") and uses:

- **Nemotron-3-Nano-30B** as the LLM, served by **Ollama** at `localhost:11434`
- **OpenClaw** (Node daemon, `ws://127.0.0.1:18789`) as the agent orchestrator
- A custom **MCP server** (in progress, Feature 2) exposing 11 domain tools
  (conjunction screening, Pc, propagation, SATCAT lookup, space weather, etc.)
- The existing Python codebase (`orbital_api`, `orbital_engine`, `orbital_data`,
  `orbital_persist`) is unchanged

The full build plan is in `PLAN.md` at the repo root. Read its "Architecture"
section (~30 lines) for the topology. This doc only covers Feature 1's
cleanup tasks.

---

## 2. Where things live on the Spark

| Thing | Location |
|---|---|
| Repo on Spark | `~/Orbital_nvidia_asus/` |
| OpenClaw main config | `~/.openclaw/openclaw.json` (with `.bak`, `.bak.1`, … backups) |
| Orbital agent state | `~/.openclaw/agents/orbital/` (agent dir + sessions) |
| Orbital agent **workspace** (markdown files injected into system prompt) | `~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace/` |
| OpenClaw gateway | systemd user service, port 18789 (already running) |
| Ollama | running, model `nemotron-3-nano:30b` already pulled |

Verify everything is up with:

```bash
openclaw status                  # gateway should be "running"
ollama list | grep nemotron      # model should be listed
python -m orbital_agent --smoke  # both checks should PASS
```

---

## 3. What's already done (don't redo)

- Python sidecar scaffolding (`orbital_agent/{__init__,config,gateway,__main__}.py`)
- Smoke test that confirms Ollama + OpenClaw reachability
- The `orbital` agent has been created with:
  ```
  openclaw agents add orbital \
    --workspace ~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace \
    --model ollama/nemotron-3-nano:30b \
    --non-interactive --json
  ```
- The agent responds to kickoff messages via:
  ```
  openclaw agent --agent orbital --json --message "..."
  ```

You can confirm at any time:

```bash
openclaw agents list                                                  # shows main + orbital
openclaw agent --agent orbital --json --message "Reply with: ready"   # returns "ready"
```

---

## 4. The two issues

When you run `openclaw agent --agent orbital --json --message "..."`, the
response JSON has a section `result.meta.systemPromptReport` that reveals
what context the model sees on each turn. Today, two things in it are wrong.

### Issue A — Tool surface is too wide

`systemPromptReport.tools.entries` lists **18 built-in tools** that come from
OpenClaw's "pi" agent harness:

```
read, edit, write, exec, process, update_plan,
sessions_list, sessions_history, sessions_send, sessions_spawn,
sessions_yield, subagents, session_status,
web_search, web_fetch, image,
memory_search, memory_get
```

These are coding-agent tools. Our agent will get 11 domain tools from the
MCP server (Feature 2): `get_flagged_conjunctions`, `get_object_metadata`,
`get_space_weather`, `get_conjunctions_for_asset`, `query_memory`,
`write_memory`, `re_propagate`, `compute_collision_probability`,
`simulate_maneuver`, `evaluate_plan`, `draft_recommendation`.

**Why this is bad:** the agent will see 29 tools total, some semantically
overlapping (`memory_search` ↔ `query_memory`, `web_fetch` ↔
`get_space_weather`). When asked "what's the current Kp index?" it may
`exec curl https://services.swpc.noaa.gov/...` instead of calling
`get_space_weather`. Tests will pass for the wrong reason and the bias will
randomly surface in Feature 3 reasoning loops.

**Also wide:** `systemPromptReport.skills.entries` lists 8 auto-enabled
skills (`browser-automation`, `healthcheck`, `node-connect`, `skill-creator`,
`taskflow`, `taskflow-inbox-triage`, `tmux`, `weather`) — another ~2,600
chars of biasing context.

### Issue B — Workspace files are auto-seeded with generic coding-agent content

When `openclaw agents add` created the agent, it auto-populated
`~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace/` with default
markdown files. Today the workspace contains:

| File | Size | What it contains | Action |
|---|---|---|---|
| `SOUL.md` | 2,194 chars | **Our content** (Orbital persona, rules, Pc thresholds, output format) | **Keep** |
| `AGENTS.md` | 7,774 chars | Generic coding-agent persona ("you are a helpful coding assistant…") | Overwrite or empty |
| `TOOLS.md` | 910 chars | Instructions describing the default coding tools | Overwrite or empty |
| `IDENTITY.md` | 693 chars | Likely "you are NVBot" name/avatar | Overwrite or empty |
| `USER.md` | 534 chars | Generic user context | Overwrite or empty |
| `HEARTBEAT.md` | 225 chars | Heartbeat config for coding agent | Overwrite or empty |
| `BOOTSTRAP.md` | (missing) | Optional bootstrap content | Leave missing |

The auto-seeded content totals ~10,000 chars of "you are a coding agent"
context that contradicts our SOUL.md and inflates every prompt by ~3,000
tokens.

---

## 5. Fix for Issue A — narrow the tool surface

OpenClaw's schema supports per-agent `tools.profile` and `skills` overrides
on each entry of `agents.list[]`. The valid profiles are:

```
"minimal" | "coding" | "messaging" | "full"
```

We want `minimal` plus an empty skills list. Sequence:

```bash
# Step 1 — confirm the orbital agent's index in agents.list (should be 1)
openclaw config get agents.list | python3 -c "
import json, sys
for i, a in enumerate(json.load(sys.stdin)):
    print(i, a.get('id'))
"
# Expected output:
#   0 main
#   1 orbital
# If orbital is at a different index, use that number below.

# Step 2 — apply the overrides
openclaw config set 'agents.list[1].tools.profile' minimal
openclaw config set 'agents.list[1].skills' '[]' --strict-json

# Step 3 — validate the resulting config
openclaw config validate
# Should print no schema errors. If it does, restore from backup
# (~/.openclaw/openclaw.json.bak) and try `openclaw config patch` instead
# (see "Plan B" below).

# Step 4 — confirm orbital is unchanged at runtime
openclaw agent --agent orbital --json --message "Reply with the single word: ok" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
sp = d['result']['meta']['systemPromptReport']
print('reply:', d['result']['payloads'][0]['text'])
print('tools count:', len(sp.get('tools', {}).get('entries', [])))
print('skills count:', len(sp.get('skills', {}).get('entries', [])))
print('prompt chars:', sp['systemPrompt']['chars'])
"
```

**Expected after Step 4:**

- `reply: ok`
- `tools count` is much smaller than 18 (ideally 0; some harness essentials
  may be inescapable — that's fine, you just want the coding tools gone)
- `skills count: 0`
- `prompt chars` is several thousand below the baseline of ~24,666

**Plan B (if `openclaw config set` rejects array-indexed paths)**

Some path libraries don't accept `agents.list[1].tools.profile`. If so,
fall back to editing the JSON directly with `jq`:

```bash
# Always back up first (OpenClaw also keeps its own .bak)
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.preorbital

# Patch with jq: find the orbital agent and merge in tools/skills
jq '(.agents.list[] | select(.id == "orbital")) |=
       (. + {tools: {profile: "minimal"}, skills: []})' \
   ~/.openclaw/openclaw.json > /tmp/openclaw.json.new

# Diff before applying
diff -u ~/.openclaw/openclaw.json /tmp/openclaw.json.new

# Apply and validate
mv /tmp/openclaw.json.new ~/.openclaw/openclaw.json
openclaw config validate
```

If validate succeeds, repeat Step 4 above to confirm.

---

## 6. Fix for Issue B — clean the workspace

The workspace dir on the Spark currently has the auto-seeded files plus our
SOUL.md. Inspect first to see what got generated:

```bash
cd ~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace
ls -la
wc -c *.md
head -40 AGENTS.md       # see how generic-coding-agent it is
head -10 IDENTITY.md     # likely "you are NVBot"
```

You have three approaches; pick whichever is cleanest. **Do not delete
SOUL.md** under any of them.

### Approach 1 (recommended) — replace with empty files

OpenClaw reads any `.md` file present in the workspace. Replacing the
auto-seeded ones with empty/near-empty content means OpenClaw still finds
them (no regeneration on next run), but they contribute zero biasing
context.

```bash
cd ~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace
for f in AGENTS.md TOOLS.md IDENTITY.md USER.md HEARTBEAT.md; do
  # Keep a single-line header so future readers know the file is intentional
  echo "<!-- intentionally minimal — see SOUL.md for the orbital agent's full identity -->" > "$f"
done
ls -la
wc -c *.md
```

### Approach 2 — delete them

Risk: OpenClaw might regenerate them on next agent invocation. Try it,
re-run the agent, and check whether the files reappear.

```bash
cd ~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace
rm AGENTS.md TOOLS.md IDENTITY.md USER.md HEARTBEAT.md
openclaw agent --agent orbital --json --message "test" >/dev/null
ls -la   # if the files are back, fall back to Approach 1
```

### Approach 3 — write Orbital-specific replacements

If you have time and want a polished agent, write tight Orbital-specific
versions:

- `AGENTS.md` (1–2 paragraphs): the operational frame — "you are running
  on a flight director's console, your output drives a human's approve/reject
  decision, the loop ends when you call `draft_recommendation`"
- `IDENTITY.md` (3–5 lines): name `Orbital`, role `flight dynamics analyst`,
  no avatar/emoji
- The rest can stay empty (Approach 1 style)

For the demo, Approach 1 is sufficient and lowest-risk.

---

## 7. Combined acceptance criteria

When both fixes are in, this command:

```bash
openclaw agent --agent orbital --json --message "Reply with: ready" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
sp = d['result']['meta']['systemPromptReport']
print('reply:', d['result']['payloads'][0]['text'])
print('model:', sp['model'])
print('workspace dir:', sp['workspaceDir'])
print()
print('=== workspace files (only SOUL.md should be a non-empty present file) ===')
for f in sp['injectedWorkspaceFiles']:
    status = 'MISSING' if f['missing'] else f\"{f['rawChars']} chars\"
    print(f\"  {f['name']}: {status}\")
print()
print('=== tools entries (should be empty or near-empty) ===')
for t in sp.get('tools', {}).get('entries', []):
    print(f\"  - {t['name']}\")
print()
print('=== skills entries (should be empty) ===')
for s in sp.get('skills', {}).get('entries', []):
    print(f\"  - {s['name']}\")
print()
print('total prompt chars:', sp['systemPrompt']['chars'])
print('input tokens:', d['result']['meta']['agentMeta']['usage']['input'])
"
```

…should print roughly:

```
reply: ready
model: nemotron-3-nano:30b
workspace dir: /home/asus/Orbital_nvidia_asus/orbital_agent/openclaw/workspace

=== workspace files (only SOUL.md should be a non-empty present file) ===
  AGENTS.md: 90 chars            # the marker line, ~90 chars
  SOUL.md: 2194 chars            # ours, unchanged
  TOOLS.md: 90 chars
  IDENTITY.md: 90 chars
  USER.md: 90 chars
  HEARTBEAT.md: 90 chars
  BOOTSTRAP.md: MISSING

=== tools entries (should be empty or near-empty) ===
  (empty list, or a couple harness essentials we can't remove)

=== skills entries (should be empty) ===
  (empty list)

total prompt chars: ~10000 (down from ~24,666 baseline)
input tokens: ~5000–7000 (down from ~11,437 baseline)
```

If the tools list still includes any of `exec`, `read`, `write`,
`web_search`, `memory_search`, `memory_get`, the profile override didn't
take effect — restore the config and try Plan B (jq edit).

---

## 8. Rollback / safety nets

OpenClaw auto-backs up `openclaw.json` on every config write:

```bash
ls ~/.openclaw/openclaw.json*
# openclaw.json
# openclaw.json.bak
# openclaw.json.bak.1
# openclaw.json.bak.2
# ...
# openclaw.json.last-good
```

If anything goes wrong:

```bash
# Roll back to the most recent backup
cp ~/.openclaw/openclaw.json.bak ~/.openclaw/openclaw.json
openclaw config validate
```

Or, full nuclear option — delete and recreate the orbital agent:

```bash
openclaw agents delete orbital
openclaw agents add orbital \
  --workspace ~/Orbital_nvidia_asus/orbital_agent/openclaw/workspace \
  --model ollama/nemotron-3-nano:30b \
  --non-interactive --json
# then re-apply Issue A's overrides
```

The orbital agent dir (`~/.openclaw/agents/orbital/`) and the workspace dir
(in the repo) are separate from `main`'s, so nuking them doesn't affect the
default `main` agent.

---

## 9. Out of scope (do NOT do these)

- **Touching the `main` agent.** It's the default `NVBot` coding agent the
  user may still want for other things on the Spark. We have our own agent
  named `orbital`.
- **Editing the MCP server.** That's Feature 2, being worked in parallel.
  Your job is to make sure the agent's tool surface is *narrow* so that
  when the MCP server lands, the only tools the model sees are the 11
  domain tools (plus whatever harness essentials are inescapable).
- **The SSE/transport layer.** That's Feature 5, later.
- **`tools.profile = "messaging"` or `"full"`.** We want `"minimal"`. Don't
  experiment with the wider profiles unless `"minimal"` fails for a clear
  reason.
- **Enabling skills.** If `minimal` profile auto-includes any skills, fine,
  but we don't want to add any explicitly. `agents.list[1].skills: []` is
  authoritative.

---

## 10. After you're done

1. Commit the workspace file changes (`AGENTS.md`, `TOOLS.md`, `IDENTITY.md`,
   `USER.md`, `HEARTBEAT.md`) — they're tracked in the repo now and the
   minimal versions become the canonical content.
2. Update PLAN.md's Feature 1 section to note that the tool profile and
   workspace overrides are applied. One sentence is enough.
3. Drop a one-line note in the team channel: "Orbital agent locked to
   minimal tools + empty skills; prompt overhead now ~Xk tokens (was 11k).
   Feature 3 unblocked."
4. Optional: open a small follow-up issue to document the per-agent config
   shape so the next person on this codebase doesn't have to re-discover it.

---

## 11. Quick reference: useful commands

```bash
# Show current orbital config (after fix should include tools.profile + skills)
openclaw config get agents.list | python3 -m json.tool

# Live gateway logs while testing
openclaw logs --follow

# Re-run our reachability check
python -m orbital_agent --smoke

# Test a kickoff and inspect the full prompt report
openclaw agent --agent orbital --json --message "test" | python3 -m json.tool | less
```

---

**Files referenced**

- `PLAN.md` (repo root) — the full build plan
- `orbital_agent/openclaw/README.md` — high-level OpenClaw notes for this repo
- `orbital_agent/openclaw/workspace/SOUL.md` — Orbital's role / rules / output format
- `~/.openclaw/openclaw.json` — main OpenClaw config (on the Spark only)
