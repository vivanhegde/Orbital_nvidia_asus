/**
 * Deterministic-per-event synthetic Pc history + matching reasoning text.
 *
 * Real Pc history is sparse and depends on screener cadence. For the demo
 * we want every conjunction to have a believable 7-day history that
 * actually tells a story (declining false-positive, rising threat,
 * geomagnetic storm spike, watch-band noise, post-maneuver resolution).
 *
 * Each event_id deterministically maps to one of 5 patterns via a seeded
 * RNG, so the same event always shows the same graph + narrative across
 * page reloads. Different events get different graphs.
 */

import type { PcHistorySnapshot, SpaceWeather } from "./types";
import type { AgentEvent, AgentEventType } from "./agentStream";

// ── Deterministic RNG ─────────────────────────────────────────────────────

function hashString(s: string): number {
  // Standard 32-bit string hash (djb2-ish). Returns an unsigned int.
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return h >>> 0;
}

/** Mulberry32 — small, fast, good distribution. Seed → 0..1 generator. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ── Pattern selection ─────────────────────────────────────────────────────

export type PcPattern =
  | "declining_dismissal"
  | "rising_action"
  | "storm_spike"
  | "oscillating_watch"
  | "maneuver_resolved";

const PATTERNS: PcPattern[] = [
  "declining_dismissal",
  "rising_action",
  "storm_spike",
  "oscillating_watch",
  "maneuver_resolved",
];

export function syntheticPattern(eventId: string): PcPattern {
  const idx = hashString(eventId) % PATTERNS.length;
  return PATTERNS[idx]!;
}

// ── Pc history generator ──────────────────────────────────────────────────

const WINDOW_DAYS = 7;
const SAMPLES_PER_DAY = 12; // every 2 hours
const TOTAL_SAMPLES = WINDOW_DAYS * SAMPLES_PER_DAY; // 84 points

interface PatternProfile {
  /** Pc(t) for t ∈ [0, 1] where 0 = start of window, 1 = now (most recent). */
  pc: (t: number, rng: () => number) => number;
  /** Optional Kp override for a given t; default uses baseline (2..3). */
  kp?: (t: number) => number;
}

const PROFILES: Record<PcPattern, PatternProfile> = {
  /** Initial conservative estimate decays as TLEs refresh. Ends below noise. */
  declining_dismissal: {
    pc: (t, rng) => {
      // log10-linear decline from -3.3 (~5e-4) to -7.5 (~3e-8) with noise.
      const trend = -3.3 - 4.2 * t;
      const noise = (rng() - 0.5) * 0.4;
      return Math.pow(10, trend + noise);
    },
  },

  /** Risk grows as TCA approaches and covariance tightens. Ends above action. */
  rising_action: {
    pc: (t, rng) => {
      // -6.3 (~5e-7) → -3.5 (~3e-4), accelerating near the end.
      const trend = -6.3 + (2.8 * t * t + 0.5 * t);
      const noise = (rng() - 0.5) * 0.35;
      return Math.pow(10, trend + noise);
    },
  },

  /** Watch-band hum until a geomagnetic storm spikes Pc, then partial decay. */
  storm_spike: {
    pc: (t, rng) => {
      // Storm centered at t≈0.45, FWHM ≈ 0.15.
      const stormCenter = 0.45;
      const stormHalfWidth = 0.15;
      const stormAmplitude = 2.5; // log10 boost
      const baseline = -5.3; // ~5e-6 watch-band hum
      const distanceFromPeak = Math.abs(t - stormCenter) / stormHalfWidth;
      const stormBoost =
        stormAmplitude * Math.exp(-distanceFromPeak * distanceFromPeak);
      // Slight decay after the storm so the tail sits a bit above baseline.
      const postStormResidual = t > stormCenter ? 0.6 * Math.exp(-(t - stormCenter) * 6) : 0;
      const noise = (rng() - 0.5) * 0.3;
      return Math.pow(10, baseline + stormBoost + postStormResidual + noise);
    },
    kp: (t) => {
      const stormCenter = 0.45;
      const stormHalfWidth = 0.15;
      const distanceFromPeak = Math.abs(t - stormCenter) / stormHalfWidth;
      const stormBoost = 4.5 * Math.exp(-distanceFromPeak * distanceFromPeak);
      return Math.min(8.5, 2.3 + stormBoost);
    },
  },

  /** Noisy walk inside the watch band, no clear trend. */
  oscillating_watch: {
    pc: (t, rng) => {
      // Two superposed sinusoids + noise around -5 (~1e-5).
      const wave1 = 0.9 * Math.sin(t * Math.PI * 3.2);
      const wave2 = 0.55 * Math.sin(t * Math.PI * 7.3 + 1.4);
      const noise = (rng() - 0.5) * 0.35;
      return Math.pow(10, -5.0 + wave1 + wave2 + noise);
    },
  },

  /** Sustained action-band Pc, then sharp drop after a maneuver mid-window. */
  maneuver_resolved: {
    pc: (t, rng) => {
      const burnTime = 0.55;
      if (t < burnTime) {
        const trend = -3.6 + (rng() - 0.5) * 0.4;
        return Math.pow(10, trend);
      }
      // Sharp post-burn decay to ~1e-9.
      const dt = (t - burnTime) / (1 - burnTime);
      const trend = -3.6 - 6.5 * dt + (rng() - 0.5) * 0.3;
      return Math.pow(10, trend);
    },
  },
};

const KP_QUIET_BASELINE = 2.3;

function defaultKp(_t: number, rng: () => number): number {
  return KP_QUIET_BASELINE + (rng() - 0.5) * 0.6;
}

function syntheticSpaceWeather(kp: number, atIso: string): SpaceWeather {
  const xray = kp >= 6 ? "M" : kp >= 5 ? "C" : kp >= 4 ? "C" : "B";
  const stormLevel =
    kp >= 7 ? "G3 Strong"
      : kp >= 6 ? "G2 Moderate"
      : kp >= 5 ? "G1 Minor"
      : kp >= 4 ? "Active"
      : "Quiet";
  return {
    kp_index: Number(kp.toFixed(2)),
    kp_trend: [],
    xray_flux_short: kp >= 6 ? 5e-6 : kp >= 5 ? 1e-6 : 3e-7,
    xray_class: xray,
    geomag_storm_level: stormLevel,
    fetched_at: atIso,
  };
}

export function syntheticPcHistory(eventId: string): PcHistorySnapshot[] {
  const rng = mulberry32(hashString(eventId + "::pc"));
  const profile = PROFILES[syntheticPattern(eventId)];
  const now = Date.now();
  const stepMs = (WINDOW_DAYS * 24 * 60 * 60 * 1000) / TOTAL_SAMPLES;
  const out: PcHistorySnapshot[] = [];

  for (let i = 0; i <= TOTAL_SAMPLES; i++) {
    const t = i / TOTAL_SAMPLES;
    const tsMs = now - (TOTAL_SAMPLES - i) * stepMs;
    const iso = new Date(tsMs).toISOString();
    const pc = Math.max(profile.pc(t, rng), 1e-12);
    const kp = profile.kp ? profile.kp(t) + (rng() - 0.5) * 0.3 : defaultKp(t, rng);
    // Miss distance is mostly geometry; small variation only.
    const miss = 0.55 + 0.4 * rng();
    // Covariance inflation rises with Kp above 5.
    const cov = kp >= 6 ? 1.4 : kp >= 5 ? 1.18 : 1.0;
    out.push({
      snapshot_at: iso,
      pc,
      miss_distance_km: miss,
      covariance_inflation: cov,
      kp_index: Number(kp.toFixed(2)),
      space_weather_snapshot: syntheticSpaceWeather(kp, iso),
    });
  }
  return out;
}

// ── Pattern → narrative reasoning ─────────────────────────────────────────

interface NarrativeEntry {
  type: AgentEventType;
  content: string | { name?: string; args?: string; summary?: string; verdict_type?: string; source_tool?: string };
  /** Seconds from the first entry — synth events get backdated by this. */
  offsetSec: number;
}

const NARRATIVES: Record<PcPattern, NarrativeEntry[]> = {
  declining_dismissal: [
    { offsetSec: 0,   type: "thought",         content: "Pulling 7-day Pc history for this asset pair." },
    { offsetSec: 18,  type: "tool_call",       content: { name: "orbital__re_propagate", args: "fresh TLE for both objects" } },
    { offsetSec: 32,  type: "tool_result",     content: { name: "orbital__re_propagate", summary: "Both TLEs <24h old; covariance ellipse tightened" } },
    { offsetSec: 52,  type: "thought",         content: "Pc trending down across the window: ~5e-4 → 3e-8. Classic stale-data false positive." },
    { offsetSec: 78,  type: "tool_call",       content: { name: "orbital__compute_collision_probability", args: "kp=2.3 (quiet)" } },
    { offsetSec: 92,  type: "tool_result",     content: { name: "orbital__compute_collision_probability", summary: "Latest Pc 3.0e-8 · band=noise · miss 0.7 km" } },
    { offsetSec: 110, type: "thought",         content: "Refined Pc well below 1e-6 noise threshold. Dismissing." },
    { offsetSec: 132, type: "verdict_drafted", content: { verdict_type: "dismissed", source_tool: "orbital__write_memory" } },
  ],

  rising_action: [
    { offsetSec: 0,   type: "thought",         content: "7-day Pc trend is clearly upward. Checking why." },
    { offsetSec: 16,  type: "tool_call",       content: { name: "orbital__get_space_weather", args: "" } },
    { offsetSec: 28,  type: "tool_result",     content: { name: "orbital__get_space_weather", summary: "Kp 2.5 · X-ray B · Quiet — drag not the driver" } },
    { offsetSec: 44,  type: "tool_call",       content: { name: "orbital__re_propagate", args: "both objects to TCA" } },
    { offsetSec: 60,  type: "tool_result",     content: { name: "orbital__re_propagate", summary: "Covariance ellipses tightening as TCA approaches; geometry is real" } },
    { offsetSec: 78,  type: "tool_call",       content: { name: "orbital__compute_collision_probability", args: "" } },
    { offsetSec: 92,  type: "tool_result",     content: { name: "orbital__compute_collision_probability", summary: "Pc 3.2e-4 · band=action · miss 0.71 km" } },
    { offsetSec: 110, type: "thought",         content: "Above 1e-4 action threshold. Evaluating two candidate burn plans." },
    { offsetSec: 134, type: "verdict_drafted", content: { verdict_type: "recommended", source_tool: "orbital__draft_recommendation" } },
  ],

  storm_spike: [
    { offsetSec: 0,   type: "thought",         content: "Pc baseline was watch-band noise until ~T-72h. Investigating spike." },
    { offsetSec: 16,  type: "tool_call",       content: { name: "orbital__get_space_weather", args: "" } },
    { offsetSec: 28,  type: "tool_result",     content: { name: "orbital__get_space_weather", summary: "Kp peaked 5.7 at T-60h · G1 Minor storm · X-ray M-class" } },
    { offsetSec: 46,  type: "thought",         content: "Storm-driven drag uncertainty inflated covariance ×1.18; Pc spiked accordingly." },
    { offsetSec: 64,  type: "tool_call",       content: { name: "orbital__compute_collision_probability", args: "kp_index=5.7" } },
    { offsetSec: 78,  type: "tool_result",     content: { name: "orbital__compute_collision_probability", summary: "Storm-window Pc 2.8e-4 · now 4.5e-5 as storm decays" } },
    { offsetSec: 96,  type: "thought",         content: "Storm subsiding; Pc back in watch band. Re-screen in 6h per protocol." },
    { offsetSec: 116, type: "verdict_drafted", content: { verdict_type: "watch", source_tool: "orbital__write_memory" } },
  ],

  oscillating_watch: [
    { offsetSec: 0,   type: "thought",         content: "Pc oscillating in watch band across the 7-day window — no trend." },
    { offsetSec: 18,  type: "tool_call",       content: { name: "orbital__re_propagate", args: "both objects" } },
    { offsetSec: 32,  type: "tool_result",     content: { name: "orbital__re_propagate", summary: "Encounter geometry sensitive to small TLE updates; persistent ambiguity" } },
    { offsetSec: 52,  type: "tool_call",       content: { name: "orbital__compute_collision_probability", args: "" } },
    { offsetSec: 66,  type: "tool_result",     content: { name: "orbital__compute_collision_probability", summary: "Pc 1.4e-5 · band=watch · miss 0.78 km" } },
    { offsetSec: 86,  type: "thought",         content: "Above noise, below action. Schedule re-screen in 6h; no maneuver yet." },
    { offsetSec: 108, type: "verdict_drafted", content: { verdict_type: "watch", source_tool: "orbital__write_memory" } },
  ],

  maneuver_resolved: [
    { offsetSec: 0,   type: "thought",         content: "History shows Pc held at action-band for ~4 days then dropped sharply." },
    { offsetSec: 18,  type: "tool_call",       content: { name: "orbital__query_memory", args: "prior verdicts for this asset" } },
    { offsetSec: 34,  type: "tool_result",     content: { name: "orbital__query_memory", summary: "Prior verdict at T-100h: recommended (approved by operator); maneuver executed T-72h" } },
    { offsetSec: 56,  type: "thought",         content: "Post-burn trajectory is what produced the sharp Pc decline. Confirming current state." },
    { offsetSec: 76,  type: "tool_call",       content: { name: "orbital__re_propagate", args: "post-maneuver state" } },
    { offsetSec: 90,  type: "tool_result",     content: { name: "orbital__re_propagate", summary: "Post-burn Pc 8.5e-9 · well below noise · miss 12.4 km" } },
    { offsetSec: 110, type: "thought",         content: "Conjunction resolved by the approved maneuver. Logging closure." },
    { offsetSec: 130, type: "verdict_drafted", content: { verdict_type: "dismissed", source_tool: "orbital__write_memory" } },
  ],
};

let _syntheticSeq = 1_000_000; // local-only key namespace, won't collide with live events

export function syntheticReasoningForEvent(eventId: string): AgentEvent[] {
  const pattern = syntheticPattern(eventId);
  const narrative = NARRATIVES[pattern];
  // Backdate so the most recent entry is "just now" and earlier ones step
  // backward by their offsets — the reader sees a recent trail.
  const lastOffset = narrative[narrative.length - 1]!.offsetSec;
  const nowMs = Date.now();
  return narrative.map((n) => {
    const tsMs = nowMs - (lastOffset - n.offsetSec) * 1000;
    return {
      type: n.type,
      content: n.content,
      related_event_id: eventId,
      timestamp: new Date(tsMs).toISOString(),
      _seq: _syntheticSeq++,
    } as AgentEvent;
  });
}

// ── Per-asset synthetic profile ───────────────────────────────────────────
//
// SATCAT doesn't publish fuel budgets, mission criticality, or operator
// notes. Each asset gets a deterministic profile derived from its NORAD ID
// so the demo shows believable per-satellite variation that stays stable
// across reloads.

export interface SyntheticAssetProfile {
  /** Total Δv budget at start of life (m/s). */
  delta_v_budget_mps: number;
  /** Fraction consumed so far (0..1). */
  fuel_used_pct: number;
  /** Remaining Δv (m/s). */
  delta_v_remaining_mps: number;
  /** Mass dry (kg). */
  mass_kg: number;
  /** Radar cross-section equivalent (m²). */
  rcs_m2: number;
  /** Mission criticality bucket. */
  mission_criticality: "critical" | "standard" | "experimental";
  /** Operator (synthesised, only for satellites not in the manual profiles). */
  operator: string;
}

const STARLINK_OPERATORS = ["SpaceX"];
const COSMOS_OPERATORS = ["—"];
const ISS_OPERATORS = ["NASA/Roscosmos"];

function pickOperator(name: string, rng: () => number): string {
  const upper = name.toUpperCase();
  if (upper.includes("STARLINK")) return STARLINK_OPERATORS[0]!;
  if (upper.includes("ISS")) return ISS_OPERATORS[0]!;
  if (upper.includes("COSMOS") || upper.includes("DEB") || upper.includes("FENGYUN"))
    return COSMOS_OPERATORS[0]!;
  // Unknown — pick one of a few plausible commercial operators
  const choices = ["Planet Labs", "OneWeb", "Iridium NEXT", "BlackSky", "Spire"];
  return choices[Math.floor(rng() * choices.length)]!;
}

export function syntheticAssetProfile(
  noradId: number,
  name: string,
  isManeuverable: boolean,
): SyntheticAssetProfile {
  const rng = mulberry32(hashString(`${noradId}::profile`));

  // Δv budget: Starlinks ~50 m/s, ISS ~hundreds, others ~10-50 m/s
  const upper = name.toUpperCase();
  let budget: number;
  if (upper.includes("ISS")) {
    budget = 280 + rng() * 60; // 280–340 m/s
  } else if (upper.includes("STARLINK")) {
    budget = 40 + rng() * 25; // 40–65 m/s
  } else if (isManeuverable) {
    budget = 18 + rng() * 35; // 18–53 m/s
  } else {
    // Non-maneuverable objects have no budget.
    return {
      delta_v_budget_mps: 0,
      fuel_used_pct: 0,
      delta_v_remaining_mps: 0,
      mass_kg: 50 + Math.floor(rng() * 1500),
      rcs_m2: Number((0.05 + rng() * 4).toFixed(2)),
      mission_criticality: "experimental",
      operator: pickOperator(name, rng),
    };
  }
  const usedPct = rng() * 0.6; // 0–60% consumed
  const remaining = budget * (1 - usedPct);

  // Mass: Starlinks ~260 kg, ISS ~420,000 kg, generic 100-2000 kg
  let mass: number;
  if (upper.includes("ISS")) mass = 420_000;
  else if (upper.includes("STARLINK")) mass = 260 + Math.floor(rng() * 40);
  else mass = 100 + Math.floor(rng() * 1900);

  // RCS: bigger satellites generally bigger RCS
  const rcs = upper.includes("ISS")
    ? 399 + rng() * 10
    : upper.includes("STARLINK")
      ? 8 + rng() * 4
      : 0.3 + rng() * 6;

  // Mission criticality
  const critRoll = rng();
  const crit =
    upper.includes("ISS")
      ? "critical"
      : critRoll < 0.15
        ? "critical"
        : critRoll < 0.85
          ? "standard"
          : "experimental";

  return {
    delta_v_budget_mps: Number(budget.toFixed(1)),
    fuel_used_pct: Number(usedPct.toFixed(2)),
    delta_v_remaining_mps: Number(remaining.toFixed(1)),
    mass_kg: mass,
    rcs_m2: Number(rcs.toFixed(2)),
    mission_criticality: crit,
    operator: pickOperator(name, rng),
  };
}

/** Heuristic — debris and rocket bodies aren't maneuverable. */
export function inferManeuverable(objectType: string | undefined): boolean {
  if (!objectType) return false;
  const t = objectType.toUpperCase();
  if (t.includes("DEB")) return false;
  if (t.includes("R/B") || t.includes("ROCKET")) return false;
  return true; // payload / unknown active object
}

export function patternSummary(pattern: PcPattern): string {
  switch (pattern) {
    case "declining_dismissal":
      return "Pc trending down — initial conservative estimate driven by stale TLE";
    case "rising_action":
      return "Pc rising as TCA approaches — covariance tightening around real miss vector";
    case "storm_spike":
      return "Geomagnetic storm spiked Pc mid-window — drag uncertainty inflated covariance";
    case "oscillating_watch":
      return "Pc oscillating in the watch band — no clear trend, persistent ambiguity";
    case "maneuver_resolved":
      return "Sharp Pc drop mid-window — operator-approved maneuver executed and resolved the conjunction";
  }
}
