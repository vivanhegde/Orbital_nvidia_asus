/** Mirrors orbital_data + orbital_api payloads (no `any`). */

export interface CatalogSummary {
  total_objects: number;
  by_group: Record<string, number>;
  newest_tle_epoch: string | null;
  oldest_tle_epoch: string | null;
}

export interface ConjunctionObj {
  norad_id: number;
  name: string;
  type: string;
}

export interface FlaggedConjunction {
  id: string;
  obj1: ConjunctionObj;
  obj2: ConjunctionObj;
  tca: string;
  miss_distance_km: number;
  relative_velocity_km_s: number;
  pc: number;
  pc_band: "noise" | "watch" | "action";
  detected_at: string;
  /** Globe camera aim from screening TCA geometry (deg). */
  camera_aim_lat?: number;
  camera_aim_lon?: number;
}

export interface FlaggedResponse {
  conjunctions: FlaggedConjunction[];
  cache_updated_at: string | null;
  screening_in_progress: boolean;
  last_error: string | null;
}

export interface SpaceWeather {
  kp_index: number;
  kp_trend: number[];
  xray_flux_short: number;
  xray_class: string;
  geomag_storm_level: string;
  fetched_at: string;
}

export type SatelliteOrbitType = "payload" | "debris" | "rocket_body";

export interface SatellitePosition {
  norad_id: number;
  name: string;
  lat: number;
  lon: number;
  alt_km: number;
  type: SatelliteOrbitType;
  source_group: string;
  path?: [number, number, number][];
}

export interface SectorDefinition {
  id: string;
  display_name: string;
  altitude_min_km: number;
  altitude_max_km: number;
  inclination_min_deg: number;
  inclination_max_deg: number;
}

export interface SectorCurrentResponse {
  sector: SectorDefinition;
  norad_ids_in_sector: number[];
  total_in_catalog: number;
}

export interface CatalogObjectResponse {
  tle: {
    name: string;
    norad_id: number;
    line1: string;
    line2: string;
    epoch: string;
    source_group: string;
    fetched_at: string;
  };
  satcat: Record<string, unknown> | null;
  propagation: {
    state_time_utc: string;
    position: {
      latitude_deg: number | null;
      longitude_deg: number | null;
      altitude_km: number | null;
      error_code: number;
    };
  };
}

/** --- Persistence / deep-link API --- */

export interface ConjunctionEventDetailResponse {
  id: string;
  obj1: ConjunctionObj;
  obj2: ConjunctionObj;
  tca: string;
  miss_distance_km: number;
  relative_velocity_km_s: number;
  pc: number;
  pc_band: "noise" | "watch" | "action";
  detected_at: string;
  status: string;
  initial_pc: number;
}

export function toFlaggedConjunction(row: ConjunctionEventDetailResponse): FlaggedConjunction {
  return {
    id: row.id,
    obj1: row.obj1,
    obj2: row.obj2,
    tca: row.tca,
    miss_distance_km: row.miss_distance_km,
    relative_velocity_km_s: row.relative_velocity_km_s,
    pc: row.pc,
    pc_band: row.pc_band,
    detected_at: row.detected_at,
  };
}

export interface PcHistorySnapshot {
  snapshot_at: string;
  pc: number;
  miss_distance_km: number;
  covariance_inflation: number;
  kp_index: number | null;
  space_weather_snapshot: SpaceWeather | null;
}

export interface PcHistoryResponse {
  snapshots: PcHistorySnapshot[];
}

export interface MemoryEventRow {
  event_id: string;
  obj1_name: string;
  obj2_name: string;
  obj1_norad_id: number;
  obj2_norad_id: number;
  tca: string;
  initial_pc: number;
  status: string;
  last_seen_at: string;
  first_detected_at: string;
}

export interface MemoryRecentResponse {
  events: MemoryEventRow[];
}

export interface MemoryAssetResponse {
  norad_id: number;
  events: MemoryEventRow[];
}

export interface ManeuverPlanOption {
  label: string;
  burns_ms?: number[];
  total_delta_v_ms?: number;
  events_resolved?: number;
}

export interface SyntheticPlanPayload {
  recommended: string;
  plans: Record<string, ManeuverPlanOption>;
  urgency?: string;
}

export interface ObjectProfile {
  norad_id: number;
  name: string | null;
  country?: string;
  object_type?: string;
  launch_date?: string | null;
  inclination_deg?: number;
  period_min?: number;
  is_maneuverable: boolean | null;
  fuel_remaining_mps: number | null;
  mission_criticality: string | null;
  operator: string | null;
}

export interface RefinementData {
  covariance_inflation: number;
  kp_index: number | null;
}

export interface AssetHistoryEntry {
  event_id: string;
  obj1_name: string;
  obj2_name: string;
  tca: string;
  initial_pc: number;
  status: string;
}

export interface VerdictEnriched {
  verdict_id: string;
  event_id: string;
  issued_at: string;
  verdict_type: string;
  reasoning: string;
  plan: SyntheticPlanPayload | null;
  operator_decision: string | null;
  operator_decided_at: string | null;
  operator_notes: string | null;
  event?: {
    obj1_name: string;
    obj2_name: string;
    obj1_norad_id: number;
    obj2_norad_id: number;
    tca: string;
    miss_distance_km?: number;
    relative_velocity_km_s?: number;
    initial_pc?: number;
    first_detected_at?: string;
  };
  current_pc?: number;
  current_miss_km?: number;
  obj1_profile?: ObjectProfile;
  obj2_profile?: ObjectProfile;
  space_weather?: SpaceWeather | null;
  refinement?: RefinementData;
  asset_history?: AssetHistoryEntry[];
}

export interface PendingVerdictsResponse {
  verdicts: VerdictEnriched[];
}
