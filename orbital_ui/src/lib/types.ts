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
