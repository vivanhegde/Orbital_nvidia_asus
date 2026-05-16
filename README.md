# Orbital

Operator dashboard for tracking objects in orbit, screening conjunctions, and surfacing space-weather context.

## Layout

| Folder | Role |
| --- | --- |
| `orbital_api/` | FastAPI HTTP server — routes for catalog, sector, conjunctions, screening, weather |
| `orbital_engine/` | Propagation + conjunction screening (SGP4, probability of collision) |
| `orbital_data/` | Data fetchers (Celestrak, NOAA SWPC), local cache, and persistence models |
| `orbital_ui/` | Vite + React + Tailwind dashboard (proxies `/api` → `127.0.0.1:8000`) |

The three Python packages share one virtualenv at the repo root.

## Prerequisites

- Python 3.10+
- Node.js 18+ (npm)

## First-time setup

Run from the repo root (`cruzhacks_2026/`).

### 1. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r orbital_api/requirements.txt
```

`orbital_api/requirements.txt` already covers the dependencies for `orbital_engine/` and `orbital_data/`, so a single install is enough.

### 2. Frontend dependencies

```bash
cd orbital_ui
npm install
cd ..
```

## Running the app

Open two terminals from the repo root.

### Terminal 1 — API server (port 8000)

```bash
source .venv/bin/activate
uvicorn orbital_api.main:app --reload --host 127.0.0.1 --port 8000
```

- API root: http://127.0.0.1:8000/
- Interactive docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

### Terminal 2 — UI dev server (port 5173)

```bash
cd orbital_ui
npm run dev
```

- Dashboard: http://localhost:5173

Vite proxies `/api/*` requests to the FastAPI server, so both must be running.

## Production build (UI)

```bash
cd orbital_ui
npm run build
npm run preview
```
