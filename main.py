from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from datetime import datetime, timedelta
import random
import os

app = FastAPI(title="FreightQuick API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "freight.db"

# ── PYDANTIC MODELS ────────────────────────────────────────────────────────

class Driver(BaseModel):
    id: Optional[int] = None
    username: str
    full_name: str
    status: Optional[str] = "available"
    driver_type: Optional[str] = "OTR"
    home_base: Optional[str] = ""
    current_location: Optional[str] = ""
    loads_completed: Optional[int] = 0
    on_time_rate: Optional[float] = 0.95

class Load(BaseModel):
    id: Optional[int] = None
    load_number: str
    origin: str
    destination: str
    pickup_date: Optional[str] = None
    delivery_date: Optional[str] = None
    weight: Optional[float] = 0
    miles: Optional[float] = 0
    rate: Optional[float] = 0
    status: Optional[str] = "available"
    load_type: Optional[str] = "OTR"
    commodity: Optional[str] = ""
    assigned_driver_id: Optional[int] = None

class Assignment(BaseModel):
    driver_id: int
    load_id: int
    match_type: Optional[str] = None

class MatchRequest(BaseModel):
    load_id: int

class OptimizeRequest(BaseModel):
    assignment_id: int

# ── DATABASE ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            status TEXT DEFAULT 'available',
            driver_type TEXT DEFAULT 'OTR',
            home_base TEXT,
            current_location TEXT,
            loads_completed INTEGER DEFAULT 0,
            on_time_rate REAL DEFAULT 0.95,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_number TEXT UNIQUE NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            pickup_date TEXT,
            delivery_date TEXT,
            weight REAL,
            miles REAL,
            rate REAL,
            status TEXT DEFAULT 'available',
            assigned_driver_id INTEGER,
            load_type TEXT DEFAULT 'OTR',
            commodity TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assigned_driver_id) REFERENCES drivers(id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            load_id INTEGER NOT NULL,
            match_score REAL DEFAULT 0.0,
            match_type TEXT,
            assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (driver_id) REFERENCES drivers(id),
            FOREIGN KEY (load_id) REFERENCES loads(id)
        );

        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            waypoints TEXT,
            total_miles REAL,
            estimated_hours REAL,
            fuel_cost REAL,
            toll_cost REAL,
            optimized_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id)
        );
    """)

    # Seed data if empty
    existing = c.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
    if existing == 0:
        drivers = [
            ("IGRAU", "Ivan Grau", "available", "OTR", "Chicago, IL", "Indianapolis, IN", 142, 0.97),
            ("LSANCHEZ", "Luis Sanchez", "on_load", "OTR", "Dallas, TX", "Memphis, TN", 218, 0.95),
            ("JTORO", "James Toro", "available", "Solo", "Atlanta, GA", "Atlanta, GA", 89, 0.93),
            ("MWILSON", "Mike Wilson", "available", "Regional", "Phoenix, AZ", "Tucson, AZ", 301, 0.98),
            ("SLEONARDS", "Sarah Leonards", "on_load", "OTR", "Seattle, WA", "Portland, OR", 176, 0.94),
            ("JRINALDI", "Joe Rinaldi", "available", "OTR", "Denver, CO", "Salt Lake City, UT", 203, 0.96),
            ("JABIAS", "Juan Abias", "available", "OTR", "Houston, TX", "New Orleans, LA", 155, 0.91),
            ("CSMITH", "Carol Smith", "off_duty", "Solo", "Miami, FL", "Miami, FL", 67, 0.99),
            ("DVARGAS", "David Vargas", "available", "Regional", "Los Angeles, CA", "San Diego, CA", 412, 0.97),
            ("MRUSSO", "Marco Russo", "on_load", "Regional", "Boston, MA", "Providence, RI", 198, 0.92),
            ("ISANCHEZ", "Isabella Sanchez", "available", "Solo", "Nashville, TN", "Louisville, KY", 88, 0.95),
        ]
        c.executemany("""INSERT INTO drivers (username, full_name, status, driver_type, home_base, current_location, loads_completed, on_time_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", drivers)

        loads = [
            ("010192-206", "Chicago, IL", "Detroit, MI", "2026-02-18", "2026-02-19", 42000, 283, 1850, "available", "OTR", "Auto Parts"),
            ("010202-476", "Dallas, TX", "Nashville, TN", "2026-02-18", "2026-02-20", 38000, 678, 2200, "available", "OTR", "Consumer Goods"),
            ("010202-477", "Atlanta, GA", "Charlotte, NC", "2026-02-19", "2026-02-19", 25000, 244, 1100, "available", "OTR", "Electronics"),
            ("010202-478", "Phoenix, AZ", "Las Vegas, NV", "2026-02-18", "2026-02-18", 18000, 297, 950, "available", "Solo", "Food & Bev"),
            ("010202-479", "Denver, CO", "Kansas City, MO", "2026-02-19", "2026-02-20", 44000, 601, 2400, "in_transit", "Regional", "Industrial"),
            ("010202-480", "Houston, TX", "San Antonio, TX", "2026-02-18", "2026-02-18", 21000, 197, 780, "available", "Regional", "Chemicals"),
            ("010207-481", "Seattle, WA", "Sacramento, CA", "2026-02-20", "2026-02-22", 36000, 750, 2800, "available", "OTR", "Tech Equipment"),
            ("010202-320", "Boston, MA", "New York, NY", "2026-02-18", "2026-02-18", 15000, 215, 890, "delivered", "Solo", "Pharmaceuticals"),
            ("010202-321", "Miami, FL", "Orlando, FL", "2026-02-19", "2026-02-19", 28000, 235, 1050, "available", "OTR", "Retail Goods"),
        ]
        c.executemany("""INSERT INTO loads (load_number, origin, destination, pickup_date, delivery_date, weight, miles, rate, status, load_type, commodity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", loads)

        # Some assignments
        c.execute("""INSERT INTO assignments (driver_id, load_id, match_score, match_type, status)
                     SELECT d.id, l.id, 0.94, 'SOURCE LOAD', 'active'
                     FROM drivers d, loads l
                     WHERE d.username='LSANCHEZ' AND l.load_number='010202-476'""")
        c.execute("""INSERT INTO assignments (driver_id, load_id, match_score, match_type, status)
                     SELECT d.id, l.id, 0.88, '4 LOAD TOUR', 'active'
                     FROM drivers d, loads l
                     WHERE d.username='SLEONARDS' AND l.load_number='010207-481'""")

        conn.commit()
    conn.close()

# ── STARTUP ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    print("🚛 FreightQuick API starting...")
    init_db()
    init_compliance_db()
    print("✅ Database initialized")

@app.get("/")
async def root():
    return {"message": "FreightQuick API", "docs": "/docs"}

# ── DRIVERS ────────────────────────────────────────────────────────────────

@app.get("/api/drivers")
async def get_drivers(status: Optional[str] = None):
    conn = get_db()
    query = "SELECT * FROM drivers"
    if status:
        query += f" WHERE status='{status}'"
    drivers = [dict(row) for row in conn.execute(query).fetchall()]
    conn.close()
    return drivers

@app.get("/api/drivers/{driver_id}")
async def get_driver(driver_id: int):
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone()
    conn.close()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return dict(driver)

@app.post("/api/drivers")
async def create_driver(driver: Driver):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO drivers (username, full_name, status, driver_type, home_base, current_location)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (driver.username, driver.full_name, driver.status, driver.driver_type, driver.home_base, driver.current_location))
    conn.commit()
    driver_id = c.lastrowid
    conn.close()
    return {"id": driver_id, "message": "Driver created"}

@app.put("/api/drivers/{driver_id}")
async def update_driver(driver_id: int, driver: Driver):
    conn = get_db()
    updates = driver.dict(exclude_unset=True, exclude={'id'})
    if updates:
        fields = ", ".join([f"{k}=?" for k in updates.keys()])
        conn.execute(f"UPDATE drivers SET {fields} WHERE id=?", (*updates.values(), driver_id))
        conn.commit()
    conn.close()
    return {"message": "Driver updated"}

# ── LOADS ──────────────────────────────────────────────────────────────────

@app.get("/api/loads")
async def get_loads(status: Optional[str] = None):
    conn = get_db()
    query = """SELECT l.*, d.username as driver_username, d.full_name as driver_name
               FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id = d.id"""
    if status:
        query += f" WHERE l.status='{status}'"
    query += " ORDER BY l.pickup_date"
    loads = [dict(row) for row in conn.execute(query).fetchall()]
    conn.close()
    return loads

@app.get("/api/loads/{load_id}")
async def get_load(load_id: int):
    conn = get_db()
    load = conn.execute("""SELECT l.*, d.username as driver_username, d.full_name as driver_name
                           FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id = d.id
                           WHERE l.id=?""", (load_id,)).fetchone()
    conn.close()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")
    return dict(load)

@app.post("/api/loads")
async def create_load(load: Load):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO loads (load_number, origin, destination, pickup_date, delivery_date, weight, miles, rate, load_type, commodity)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (load.load_number, load.origin, load.destination, load.pickup_date, load.delivery_date,
               load.weight, load.miles, load.rate, load.load_type, load.commodity))
    conn.commit()
    load_id = c.lastrowid
    conn.close()
    return {"id": load_id, "message": "Load created"}

@app.put("/api/loads/{load_id}")
async def update_load(load_id: int, load: Load):
    conn = get_db()
    updates = load.dict(exclude_unset=True, exclude={'id'})
    if updates:
        fields = ", ".join([f"{k}=?" for k in updates.keys()])
        conn.execute(f"UPDATE loads SET {fields} WHERE id=?", (*updates.values(), load_id))
        conn.commit()
    conn.close()
    return {"message": "Load updated"}

# ── ASSIGNMENTS ────────────────────────────────────────────────────────────

@app.get("/api/assignments")
async def get_assignments():
    conn = get_db()
    assignments = [dict(row) for row in conn.execute("""
        SELECT a.*, d.username, d.full_name, d.status as driver_status,
               l.load_number, l.origin, l.destination, l.rate, l.miles
        FROM assignments a
        JOIN drivers d ON a.driver_id = d.id
        JOIN loads l ON a.load_id = l.id
        ORDER BY a.assigned_at DESC
    """).fetchall()]
    conn.close()
    return assignments

@app.post("/api/assignments")
async def create_assignment(assignment: Assignment):
    driver_id = assignment.driver_id
    load_id = assignment.load_id

    conn = get_db()
    # Calculate mock match score
    match_score = round(random.uniform(0.80, 0.99), 2)
    match_types = ["SOURCE LOAD", "4 LOAD TOUR", "1HR TO SOURCE", "SOURCE TOUR"]
    match_type = assignment.match_type or random.choice(match_types)

    c = conn.cursor()
    c.execute("""INSERT INTO assignments (driver_id, load_id, match_score, match_type)
                 VALUES (?, ?, ?, ?)""", (driver_id, load_id, match_score, match_type))

    # Update driver and load status
    conn.execute("UPDATE drivers SET status='on_load' WHERE id=?", (driver_id,))
    conn.execute("UPDATE loads SET status='assigned', assigned_driver_id=? WHERE id=?", (driver_id, load_id))

    conn.commit()
    assignment_id = c.lastrowid

    # Auto-generate route
    load = dict(conn.execute("SELECT * FROM loads WHERE id=?", (load_id,)).fetchone())
    route_miles = load["miles"]
    conn.execute("""INSERT INTO routes (assignment_id, total_miles, estimated_hours, fuel_cost, toll_cost)
                    VALUES (?, ?, ?, ?, ?)""",
                 (assignment_id, route_miles,
                  round(route_miles / 55, 1),
                  round(route_miles * 0.43, 2),
                  round(route_miles * 0.08, 2)))
    conn.commit()
    conn.close()
    return {"id": assignment_id, "match_score": match_score, "match_type": match_type}

# ── MATCH ENGINE ───────────────────────────────────────────────────────────

@app.post("/api/match")
async def match_drivers(request: MatchRequest):
    """Return optimal driver matches for a given load"""
    load_id = request.load_id

    conn = get_db()
    load = dict(conn.execute("SELECT * FROM loads WHERE id=?", (load_id,)).fetchone())
    available_drivers = [dict(r) for r in conn.execute(
        "SELECT * FROM drivers WHERE status='available' ORDER BY on_time_rate DESC"
    ).fetchall()]
    conn.close()

    match_types = ["SOURCE LOAD", "4 LOAD TOUR", "1HR TO SOURCE", "SOURCE TOUR"]
    matches = []
    for i, d in enumerate(available_drivers[:5]):
        score = round(d["on_time_rate"] * random.uniform(0.88, 1.0), 2)
        matches.append({
            **d,
            "match_score": score,
            "match_type": match_types[i % len(match_types)],
            "eta_to_pickup": f"{random.randint(1,8)}h {random.randint(0,59)}m"
        })

    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return {"load": load, "matches": matches}

# ── ROUTES ─────────────────────────────────────────────────────────────────

@app.get("/api/routes")
async def get_routes():
    conn = get_db()
    routes = [dict(row) for row in conn.execute("""
        SELECT r.*, a.match_type, a.status as assignment_status,
               d.username, d.full_name,
               l.load_number, l.origin, l.destination
        FROM routes r
        JOIN assignments a ON r.assignment_id = a.id
        JOIN drivers d ON a.driver_id = d.id
        JOIN loads l ON a.load_id = l.id
    """).fetchall()]
    conn.close()
    return routes

@app.post("/api/routes/optimize")
async def optimize_route(request: OptimizeRequest):
    """Recalculate optimal route for an assignment"""
    assignment_id = request.assignment_id
    conn = get_db()
    route = dict(conn.execute("SELECT * FROM routes WHERE assignment_id=?", (assignment_id,)).fetchone())
    # Simulate optimization savings (3-8% improvement)
    savings_pct = random.uniform(0.03, 0.08)
    new_miles = round(route["total_miles"] * (1 - savings_pct), 1)
    new_fuel = round(new_miles * 0.43, 2)
    conn.execute("""UPDATE routes SET total_miles=?, estimated_hours=?, fuel_cost=? WHERE assignment_id=?""",
                 (new_miles, round(new_miles / 55, 1), new_fuel, assignment_id))
    conn.commit()
    conn.close()
    return {"optimized": True, "savings_miles": round(route["total_miles"] - new_miles, 1), "new_total": new_miles}

# ── ANALYTICS ──────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics():
    conn = get_db()

    total_drivers = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]
    available_drivers = conn.execute("SELECT COUNT(*) FROM drivers WHERE status='available'").fetchone()[0]
    active_loads = conn.execute("SELECT COUNT(*) FROM loads WHERE status IN ('available','assigned','in_transit')").fetchone()[0]
    total_revenue = conn.execute("SELECT COALESCE(SUM(rate),0) FROM loads WHERE status='delivered'").fetchone()[0]
    active_assignments = conn.execute("SELECT COUNT(*) FROM assignments WHERE status='active'").fetchone()[0]
    avg_on_time = conn.execute("SELECT AVG(on_time_rate) FROM drivers").fetchone()[0]
    total_miles = conn.execute("SELECT COALESCE(SUM(total_miles),0) FROM routes").fetchone()[0]
    fuel_cost = conn.execute("SELECT COALESCE(SUM(fuel_cost),0) FROM routes").fetchone()[0]

    # Daily revenue trend (mock last 14 days)
    today = datetime.now()
    daily_trend = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        daily_trend.append({
            "date": day.strftime("%m/%d"),
            "revenue": round(random.uniform(18000, 42000), 0),
            "loads": random.randint(4, 14),
            "miles": random.randint(2000, 6000)
        })

    # Driver utilization by type
    utilization = [dict(r) for r in conn.execute("""
        SELECT driver_type, COUNT(*) as total,
               SUM(CASE WHEN status='on_load' THEN 1 ELSE 0 END) as active
        FROM drivers GROUP BY driver_type
    """).fetchall()]

    conn.close()
    return {
        "summary": {
            "total_drivers": total_drivers,
            "available_drivers": available_drivers,
            "utilization_rate": round((total_drivers - available_drivers) / max(total_drivers, 1) * 100, 1),
            "active_loads": active_loads,
            "active_assignments": active_assignments,
            "total_revenue": round(total_revenue, 2),
            "avg_on_time_rate": round((avg_on_time or 0) * 100, 1),
            "total_miles": round(total_miles, 1),
            "total_fuel_cost": round(fuel_cost, 2)
        },
        "daily_trend": daily_trend,
        "driver_utilization": utilization
    }
# ── DOT COMPLIANCE ─────────────────────────────────────────────────────────

class ComplianceRecord(BaseModel):
    driver_id: int
    cdl_expiry: Optional[str] = None
    medical_card_expiry: Optional[str] = None
    mvr_date: Optional[str] = None
    drug_test_date: Optional[str] = None
    annual_inspection_expiry: Optional[str] = None
    notes: Optional[str] = ""

def init_compliance_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compliance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER UNIQUE NOT NULL,
            cdl_expiry TEXT,
            medical_card_expiry TEXT,
            mvr_date TEXT,
            drug_test_date TEXT,
            annual_inspection_expiry TEXT,
            notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    conn.commit()
    conn.close()

def get_compliance_status(expiry_date: str):
    if not expiry_date:
        return "missing"
    try:
        exp = datetime.strptime(expiry_date, "%Y-%m-%d")
        days_left = (exp - datetime.now()).days
        if days_left < 0:
            return "expired"
        elif days_left <= 30:
            return "expiring_soon"
        else:
            return "ok"
    except:
        return "missing"

@app.get("/api/compliance")
async def get_compliance():
    conn = get_db()
    records = [dict(row) for row in conn.execute("""
        SELECT c.*, d.username, d.full_name, d.driver_type
        FROM compliance c
        JOIN drivers d ON c.driver_id = d.id
        ORDER BY d.full_name
    """).fetchall()]
    conn.close()
    result = []
    for r in records:
        r["cdl_status"] = get_compliance_status(r["cdl_expiry"])
        r["medical_status"] = get_compliance_status(r["medical_card_expiry"])
        r["inspection_status"] = get_compliance_status(r["annual_inspection_expiry"])
        r["drug_test_status"] = get_compliance_status(r["drug_test_date"])
        result.append(r)
    return result

@app.post("/api/compliance")
async def create_compliance(record: ComplianceRecord):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO compliance 
        (driver_id, cdl_expiry, medical_card_expiry, mvr_date, drug_test_date, annual_inspection_expiry, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (record.driver_id, record.cdl_expiry, record.medical_card_expiry,
          record.mvr_date, record.drug_test_date, record.annual_inspection_expiry,
          record.notes, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    return {"message": "Compliance record saved"}

@app.get("/api/compliance/summary")
async def compliance_summary():
    conn = get_db()
    records = [dict(row) for row in conn.execute("SELECT * FROM compliance").fetchall()]
    conn.close()
    total = len(records)
    expired = sum(1 for r in records if get_compliance_status(r["cdl_expiry"]) == "expired" or
                  get_compliance_status(r["medical_card_expiry"]) == "expired")
    expiring = sum(1 for r in records if get_compliance_status(r["cdl_expiry"]) == "expiring_soon" or
                   get_compliance_status(r["medical_card_expiry"]) == "expiring_soon")
    return {"total": total, "expired": expired, "expiring_soon": expiring, "compliant": total - expired - expiring}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
