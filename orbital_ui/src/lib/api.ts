import type {
  CatalogObjectResponse,
  CatalogSummary,
  ConjunctionEventDetailResponse,
  FlaggedResponse,
  MemoryAssetResponse,
  MemoryRecentResponse,
  PcHistoryResponse,
  PendingVerdictsResponse,
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

const JSON_HDR = {
  Accept: "application/json",
  "Content-Type": "application/json",
};

export async function getPcHistory(
  eventId: string,
  hours: number,
): Promise<PcHistoryResponse> {
  const q = new URLSearchParams({ hours: String(hours) });
  return apiGet<PcHistoryResponse>(
    `/api/conjunctions/${encodeURIComponent(eventId)}/pc-history?${q}`,
  );
}

export async function getConjunctionEvent(
  eventId: string,
): Promise<ConjunctionEventDetailResponse> {
  return apiGet<ConjunctionEventDetailResponse>(
    `/api/conjunctions/event/${encodeURIComponent(eventId)}`,
  );
}

export async function getMemoryRecent(limit = 50): Promise<MemoryRecentResponse> {
  return apiGet<MemoryRecentResponse>(`/api/memory/recent?limit=${limit}`);
}

export async function getMemoryAsset(
  noradId: number,
  limit = 20,
): Promise<MemoryAssetResponse> {
  return apiGet<MemoryAssetResponse>(
    `/api/memory/asset/${noradId}?limit=${limit}`,
  );
}

export async function getPendingVerdicts(): Promise<PendingVerdictsResponse> {
  return apiGet<PendingVerdictsResponse>("/api/verdicts/pending");
}

export async function approveVerdict(
  verdictId: string,
  notes?: string,
): Promise<unknown> {
  const res = await fetch(
    `/api/verdicts/${encodeURIComponent(verdictId)}/approve`,
    {
      method: "POST",
      headers: JSON_HDR,
      body: JSON.stringify({ notes: notes ?? null }),
    },
  );
  if (!res.ok) {
    throw new Error(`approve failed: ${res.status}`);
  }
  return res.json();
}

export async function rejectVerdict(
  verdictId: string,
  notes?: string,
): Promise<unknown> {
  const res = await fetch(
    `/api/verdicts/${encodeURIComponent(verdictId)}/reject`,
    {
      method: "POST",
      headers: JSON_HDR,
      body: JSON.stringify({ notes: notes ?? null }),
    },
  );
  if (!res.ok) {
    throw new Error(`reject failed: ${res.status}`);
  }
  return res.json();
}

export async function synthesizeDemoVerdict(
  eventId: string,
): Promise<{ verdict_id: string }> {
  const res = await fetch("/api/dev/synthesize-verdict", {
    method: "POST",
    headers: JSON_HDR,
    body: JSON.stringify({ event_id: eventId }),
  });
  if (!res.ok) {
    throw new Error(`synthesize failed: ${res.status}`);
  }
  return res.json() as Promise<{ verdict_id: string }>;
}
