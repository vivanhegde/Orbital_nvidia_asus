"""Force screening refresh."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Response

from orbital_api.cache import screening_cache
from orbital_api.screening_jobs import run_screening_job

router = APIRouter(prefix="/api/screening", tags=["screening"])


@router.post("/refresh")
def screening_refresh() -> Response:
    threading.Thread(
        target=run_screening_job,
        args=(screening_cache,),
        name="orbital-screening-refresh",
        daemon=True,
    ).start()
    return Response(status_code=202)
