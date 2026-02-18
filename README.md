# FreightQuick — Lightning-Fast Dispatch Automation

A full-stack freight dispatch management platform built with **FastAPI** and **React**.
Features instant driver matching, load management, route optimization, and real-time analytics.

## 🚀 Quick Start

### 1. Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
python main.py
```

The API runs at **http://localhost:8000**

**View auto-generated API docs:** http://localhost:8000/docs

### 2. Frontend

Open `frontend/landing.html` in your browser for the marketing page.
Open `frontend/app.html` for the full dispatch dashboard.

> The dashboard works standalone with mock data even without the backend running.
> Connect the backend to enable full CRUD operations.

---

## 📁 Project Structure

```
freight-quick/
├── backend/
│   ├── main.py              # FastAPI REST API + SQLite
│   └── requirements.txt
└── frontend/
    ├── landing.html         # Marketing landing page
    └── app.html             # Full dispatch dashboard (React)
```

---

## 🔌 API Endpoints

FastAPI automatically generates interactive API documentation at `/docs`.

### Drivers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/drivers` | List all drivers |
| GET | `/api/drivers?status=available` | Filter by status |
| GET | `/api/drivers/{id}` | Get single driver |
| POST | `/api/drivers` | Create driver |
| PUT | `/api/drivers/{id}` | Update driver |

### Loads
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/loads` | List all loads |
| GET | `/api/loads?status=available` | Filter by status |
| POST | `/api/loads` | Create load |
| PUT | `/api/loads/{id}` | Update load |

### Dispatch & Matching
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/assignments` | List all assignments |
| POST | `/api/assignments` | Assign driver to load |
| POST | `/api/match` | Get optimal driver matches for a load |

### Routes
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/routes` | List all routes |
| POST | `/api/routes/optimize` | Re-optimize a route |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics` | Full analytics summary + trends |

---

## 🎛️ Dashboard Features

### 📊 Analytics
- Live KPI cards: utilization, active loads, on-time rate, miles
- 14-day revenue trend chart
- Driver utilization breakdown by type (OTR / Regional / Solo)

### ⚡ Dispatch
- Browse available loads on the left
- Click a load → AI-powered driver matching scores appear on the right
- Select one or more drivers → click "Assign to Driver"
- Match types: SOURCE LOAD, 4 LOAD TOUR, 1HR TO SOURCE, SOURCE TOUR

### 📦 Loads
- Full load table with filtering by status
- Search by load number, origin, or destination
- Add new loads with the form

### 👤 Drivers
- Card grid view of all drivers
- Color-coded status (available / on load / off duty)
- Add new drivers with the form

### 🗺️ Routes
- View active routes with miles, hours, fuel & toll estimates
- Click "Optimize Route" to run route optimization
- Visual route bar with waypoints

---

## 🏗️ Why FastAPI?

FastAPI advantages over Flask:
- **Auto-generated API docs** at `/docs` (Swagger UI)
- **Type safety** with Pydantic models
- **Async support** for better performance
- **Built-in validation** for request/response
- **Modern Python** (3.7+ with type hints)

---

## 🛠️ Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python · FastAPI · Uvicorn · SQLite |
| Frontend | React 18 · Recharts |
| Styling | Pure CSS custom properties |
| Fonts | Archivo · IBM Plex Mono · Inter |

---

## 🚀 Deployment

### Render (Free Tier)
```yaml
# render.yaml
services:
  - type: web
    name: freightquick-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PORT
        value: 8000
```

### Railway
```bash
railway up
```
Auto-detects FastAPI and configures automatically.

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 🔗 Production Roadmap

- [ ] Add JWT authentication
- [ ] Integrate real TMS (McLeod, TMW, Aljex)
- [ ] Connect Google Maps API for real routing
- [ ] Add WebSocket for real-time updates
- [ ] Build mobile driver app
- [ ] Add ML-based match scoring model
- [ ] Deploy with PostgreSQL + Redis

---

## 📖 API Documentation

Once running, visit:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

FastAPI generates these automatically from your code!

---

## ⚡ FreightQuick vs FreightOS

This is a FastAPI rewrite of the original FreightOS platform, featuring:
- 🚀 **Faster** — Async operations + type safety
- 📚 **Better docs** — Auto-generated API docs
- 🔒 **Type-safe** — Pydantic models catch errors early
- ⚡ **Modern** — Python 3.11+ with latest FastAPI patterns
