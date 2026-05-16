"""FastAPI dependencies shared across routers."""

from __future__ import annotations

from fastapi import HTTPException

from orbital_api.screening_jobs import get_event_store
from orbital_persist.store import EventStore


def require_event_store() -> EventStore:
    store = get_event_store()
    if store is None:
        raise HTTPException(status_code=503, detail="EventStore not initialized")
    return store
