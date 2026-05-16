import type {
  CatalogObjectResponse,
  CatalogSummary,
  FlaggedResponse,
  SatellitePosition,
  SectorCurrentResponse,
  SpaceWeather,
} from "./types";

export const ACTIVE_SECTOR_ID = "starlink-550";

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function getCatalogSummary(): Promise<CatalogSummary> {
  return apiGet<CatalogSummary>("/api/catalog/summary");
}

export async function getFlaggedConjunctions(): Promise<FlaggedResponse> {
  return apiGet<FlaggedResponse>("/api/conjunctions/flagged");
}

export async function getSpaceWeather(): Promise<SpaceWeather> {
  const res = await fetch("/api/space-weather", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`GET /api/space-weather failed: ${res.status}`);
  }
  return res.json() as Promise<SpaceWeather>;
}

export async function postScreeningRefresh(): Promise<void> {
  const res = await fetch("/api/screening/refresh", { method: "POST" });
  if (res.status !== 202) {
    throw new Error(`POST refresh failed: ${res.status}`);
  }
}

export async function getCatalogObject(
  noradId: number,
): Promise<CatalogObjectResponse> {
  return apiGet<CatalogObjectResponse>(`/api/catalog/object/${noradId}`);
}

export async function getSectorCurrent(
  sectorId: string = ACTIVE_SECTOR_ID,
): Promise<SectorCurrentResponse> {
  const sp = new URLSearchParams({ sector_id: sectorId });
  return apiGet<SectorCurrentResponse>(`/api/sector/current?${sp.toString()}`);
}

export async function getCatalogPositions(params: {
  limit?: number;
  groups?: string[];
  sector?: string | null;
  includePaths?: boolean;
}): Promise<SatellitePosition[]> {
  const sp = new URLSearchParams();
  const lim = params.limit ?? 500;
  sp.set("limit", String(lim));
  if (params.groups?.length) {
    for (const g of params.groups) {
      sp.append("groups", g);
    }
  }
  if (params.sector) {
    sp.set("sector", params.sector);
  }
  if (params.includePaths) {
    sp.set("include_paths", "true");
  }
  const path = `/api/catalog/positions?${sp.toString()}`;
  return apiGet<SatellitePosition[]>(path);
}

export async function getCatalogPositionsNoradsAt(
  noradIds: number[],
  atIso: string,
): Promise<SatellitePosition[]> {
  const sp = new URLSearchParams();
  sp.set("norad_ids", noradIds.join(","));
  sp.set("at", atIso);
  return apiGet<SatellitePosition[]>(`/api/catalog/positions?${sp.toString()}`);
}
