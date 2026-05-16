"""FastAPI entrypoint for Orbital operator dashboard."""

from __future__ import annotations

import logging
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OD = _ROOT / "orbital_data"
for _p in (_OD, _ROOT):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orbital_api.agent_bus import AgentEventBus
from orbital_api.cache import screening_cache
from orbital_api.positions import warm_default_sector_positions
from orbital_api.routes import (
    agent_route,
    catalog,
    conjunction_history,
    conjunctions,
    dev_route,
    memory_route,
    screening_route,
    sector_route,
    verdicts_route,
    weather,
)
from orbital_api.screening_jobs import configure_event_store
from orbital_persist.store import EventStore

logging.basicConfig(level=logging.INFO)

_EVENT_DB = _ROOT / "orbital_data" / "orbital.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    event_store = EventStore(_EVENT_DB)
    configure_event_store(event_store)
    app.state.event_store = event_store
    app.state.agent_bus = AgentEventBus()
    screening_cache.start_worker(60.0)
    threading.Thread(target=warm_default_sector_positions, daemon=True).start()
    yield
    screening_cache.stop_worker()
    event_store.close()


app = FastAPI(title="Orbital API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(sector_route.router)
app.include_router(conjunctions.router)
app.include_router(conjunction_history.router)
app.include_router(weather.router)
app.include_router(screening_route.router)
app.include_router(memory_route.router)
app.include_router(verdicts_route.router)
app.include_router(dev_route.router)
app.include_router(agent_route.router)


@app.get("/")
def root() -> dict[str, object]:
    """Landing when visiting the API host in a browser (paths live under /api/…)."""
    return {
        "service": "Orbital API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
        "endpoints": {
            "catalog_summary": "/api/catalog/summary",
            "catalog_positions": "/api/catalog/positions",
            "catalog_object": "/api/catalog/object/{norad_id}",
            "sector_current": "/api/sector/current",
            "conjunctions_flagged": "/api/conjunctions/flagged",
            "conjunctions_event": "/api/conjunctions/event/{event_id}",
            "pc_history": "/api/conjunctions/{event_id}/pc-history",
            "memory_recent": "/api/memory/recent",
            "memory_asset": "/api/memory/asset/{norad_id}",
            "verdicts_pending": "/api/verdicts/pending",
            "dev_synthesize": "POST /api/dev/synthesize-verdict",
            "space_weather": "/api/space-weather",
            "screening_refresh": "POST /api/screening/refresh",
            "agent_stream": "GET /api/agent/stream (SSE)",
            "agent_event": "POST /api/agent/event",
            "agent_stats": "GET /api/agent/stats",
        },
        "ui": "Run orbital_ui (npm run dev) at http://localhost:5173 for the dashboard.",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
