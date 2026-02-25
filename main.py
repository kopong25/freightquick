from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import requests as http_requests
import random
import os
import hashlib
import secrets
import stripe
STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY")
stripe.api_key = STRIPE_KEY
import resend
resend.api_key = os.environ.get("RESEND_API_KEY")

app = FastAPI(title="FreightQuick API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL")

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

class ComplianceRecord(BaseModel):
    driver_id: int
    cdl_expiry: Optional[str] = None
    medical_card_expiry: Optional[str] = None
    mvr_date: Optional[str] = None
    drug_test_date: Optional[str] = None
    annual_inspection_expiry: Optional[str] = None
    notes: Optional[str] = ""

class PayRecord(BaseModel):
    driver_id: int
    load_id: Optional[int] = None
    week_ending: str
    gross_pay: float
    fuel_deduction: Optional[float] = 0
    insurance_deduction: Optional[float] = 0
    advance_deduction: Optional[float] = 0
    other_deduction: Optional[float] = 0
    notes: Optional[str] = ""

class InsurancePolicy(BaseModel):
    truck_number: str
    policy_number: str
    provider: str
    policy_type: str
    premium: float
    expiry_date: str
    coverage_amount: Optional[float] = 0
    notes: Optional[str] = ""

class CompanySignup(BaseModel):
    company_name: str
    dot_number: Optional[str] = ""
    email: str
    password: str
    full_name: str

class UserLogin(BaseModel):
    email: str
    password: str

class InviteDriver(BaseModel):
    email: str
    full_name: str
    company_id: int

# ── DATABASE ───────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_compliance_status(expiry_date):
    if not expiry_date:
        return "missing"
    try:
        exp = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d")
        days_left = (exp - datetime.now()).days
        if days_left < 0:
            return "expired"
        elif days_left <= 30:
            return "expiring_soon"
        else:
            return "ok"
    except:
        return "missing"

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            id SERIAL PRIMARY KEY,
            company_id INTEGER DEFAULT 1,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            status TEXT DEFAULT 'available',
            driver_type TEXT DEFAULT 'OTR',
            home_base TEXT,
            current_location TEXT,
            loads_completed INTEGER DEFAULT 0,
            on_time_rate REAL DEFAULT 0.95,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS loads (
            id SERIAL PRIMARY KEY,
            company_id INTEGER DEFAULT 1,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            load_id INTEGER NOT NULL,
            match_score REAL DEFAULT 0.0,
            match_type TEXT,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            id SERIAL PRIMARY KEY,
            assignment_id INTEGER NOT NULL,
            waypoints TEXT,
            total_miles REAL,
            estimated_hours REAL,
            fuel_cost REAL,
            toll_cost REAL,
            optimized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS compliance (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER UNIQUE NOT NULL,
            cdl_expiry TEXT,
            medical_card_expiry TEXT,
            mvr_date TEXT,
            drug_test_date TEXT,
            annual_inspection_expiry TEXT,
            notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pay_records (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            load_id INTEGER,
            week_ending TEXT NOT NULL,
            gross_pay REAL DEFAULT 0,
            fuel_deduction REAL DEFAULT 0,
            insurance_deduction REAL DEFAULT 0,
            advance_deduction REAL DEFAULT 0,
            other_deduction REAL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS insurance_policies (
            id SERIAL PRIMARY KEY,
            truck_number TEXT NOT NULL,
            policy_number TEXT NOT NULL,
            provider TEXT NOT NULL,
            policy_type TEXT NOT NULL,
            premium REAL DEFAULT 0,
            expiry_date TEXT NOT NULL,
            coverage_amount REAL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            company_name TEXT NOT NULL,
            dot_number TEXT,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trial_ends_at TIMESTAMP,
            is_subscribed INTEGER DEFAULT 0
        )
    """)
    # Add trial columns if they don't exist
    c.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP")
    c.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_subscribed INTEGER DEFAULT 0")

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'driver',
            invite_token TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inspections (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            driver_id INTEGER,
            driver_name TEXT,
            vehicle TEXT,
            status TEXT DEFAULT 'clear',
            damage_items TEXT,
            gps_location TEXT,
            notes TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS fuel_entries (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            driver_id INTEGER,
            driver_name TEXT,
            vehicle TEXT,
            state TEXT,
            gallons NUMERIC,
            price_per_gallon NUMERIC,
            total_cost NUMERIC,
            odometer INTEGER,
            fuel_date DATE,
            fuel_type TEXT DEFAULT 'diesel',
            vendor TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_miles (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            vehicle TEXT,
            driver_name TEXT,
            state TEXT,
            miles NUMERIC,
            trip_date DATE,
            load_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed drivers if empty
    c.execute("SELECT COUNT(*) FROM drivers")
    if c.fetchone()[0] == 0:
        drivers = [
            ("IGRAU","Ivan Grau","available","OTR","Chicago, IL","Indianapolis, IN",142,0.97),
            ("LSANCHEZ","Luis Sanchez","on_load","OTR","Dallas, TX","Memphis, TN",218,0.95),
            ("JTORO","James Toro","available","Solo","Atlanta, GA","Atlanta, GA",89,0.93),
            ("MWILSON","Mike Wilson","available","Regional","Phoenix, AZ","Tucson, AZ",301,0.98),
            ("SLEONARDS","Sarah Leonards","on_load","OTR","Seattle, WA","Portland, OR",176,0.94),
            ("JRINALDI","Joe Rinaldi","available","OTR","Denver, CO","Salt Lake City, UT",203,0.96),
            ("JABIAS","Juan Abias","available","OTR","Houston, TX","New Orleans, LA",155,0.91),
            ("CSMITH","Carol Smith","off_duty","Solo","Miami, FL","Miami, FL",67,0.99),
            ("DVARGAS","David Vargas","available","Regional","Los Angeles, CA","San Diego, CA",412,0.97),
            ("MRUSSO","Marco Russo","on_load","Regional","Boston, MA","Providence, RI",198,0.92),
            ("ISANCHEZ","Isabella Sanchez","available","Solo","Nashville, TN","Louisville, KY",88,0.95),
        ]
        for d in drivers:
            c.execute("""INSERT INTO drivers (username,full_name,status,driver_type,home_base,current_location,loads_completed,on_time_rate)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", d)

    c.execute("SELECT COUNT(*) FROM loads")
    if c.fetchone()[0] == 0:
        loads = [
            ("010192-206","Chicago, IL","Detroit, MI","2026-02-18","2026-02-19",42000,283,1850,"available","OTR","Auto Parts"),
            ("010202-476","Dallas, TX","Nashville, TN","2026-02-18","2026-02-20",38000,678,2200,"available","OTR","Consumer Goods"),
            ("010202-477","Atlanta, GA","Charlotte, NC","2026-02-19","2026-02-19",25000,244,1100,"available","OTR","Electronics"),
            ("010202-478","Phoenix, AZ","Las Vegas, NV","2026-02-18","2026-02-18",18000,297,950,"available","Solo","Food & Bev"),
            ("010202-479","Denver, CO","Kansas City, MO","2026-02-19","2026-02-20",44000,601,2400,"in_transit","Regional","Industrial"),
            ("010202-480","Houston, TX","San Antonio, TX","2026-02-18","2026-02-18",21000,197,780,"available","Regional","Chemicals"),
            ("010207-481","Seattle, WA","Sacramento, CA","2026-02-20","2026-02-22",36000,750,2800,"available","OTR","Tech Equipment"),
            ("010202-320","Boston, MA","New York, NY","2026-02-18","2026-02-18",15000,215,890,"delivered","Solo","Pharmaceuticals"),
            ("010202-321","Miami, FL","Orlando, FL","2026-02-19","2026-02-19",28000,235,1050,"available","OTR","Retail Goods"),
        ]
        for l in loads:
            c.execute("""INSERT INTO loads (load_number,origin,destination,pickup_date,delivery_date,weight,miles,rate,status,load_type,commodity)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", l)
    # Add company_id columns if they don't exist
    c.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS company_id INTEGER DEFAULT 1")
    c.execute("ALTER TABLE loads ADD COLUMN IF NOT EXISTS company_id INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

# ── STARTUP ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    print("🚛 FreightQuick API starting...")
    init_db()
    print("✅ Database initialized")

@app.get("/")
async def root():
    return {"message": "FreightQuick API", "docs": "/docs"}

# ── DRIVERS ────────────────────────────────────────────────────────────────

@app.get("/api/drivers")
async def get_drivers(status: Optional[str] = None, company_id: Optional[int] = None):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if company_id and status:
        c.execute("SELECT * FROM drivers WHERE company_id=%s AND status=%s", (company_id, status))
    elif company_id:
        c.execute("SELECT * FROM drivers WHERE company_id=%s", (company_id,))
    elif status:
        c.execute("SELECT * FROM drivers WHERE status=%s", (status,))
    else:
        c.execute("SELECT * FROM drivers")
    drivers = c.fetchall()
    conn.close()
    return [dict(d) for d in drivers]

@app.post("/api/drivers")
async def create_driver(driver: Driver):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO drivers (username,full_name,status,driver_type,home_base,current_location)
                 VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
              (driver.username,driver.full_name,driver.status,driver.driver_type,driver.home_base,driver.current_location))
    driver_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return {"id": driver_id, "message": "Driver created"}

@app.put("/api/drivers/{driver_id}")
async def update_driver(driver_id: int, driver: Driver):
    conn = get_db()
    c = conn.cursor()
    updates = driver.dict(exclude_unset=True, exclude={'id'})
    if updates:
        fields = ", ".join([f"{k}=%s" for k in updates.keys()])
        c.execute(f"UPDATE drivers SET {fields} WHERE id=%s", (*updates.values(), driver_id))
        conn.commit()
    conn.close()
    return {"message": "Driver updated"}

# ── LOADS ──────────────────────────────────────────────────────────────────

@app.get("/api/loads")
async def get_loads(status: Optional[str] = None, company_id: Optional[int] = None):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if company_id and status:
        c.execute("""SELECT l.*,d.username as driver_username,d.full_name as driver_name
                     FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id=d.id
                     WHERE l.company_id=%s AND l.status=%s ORDER BY l.pickup_date""", (company_id, status))
    elif company_id:
        c.execute("""SELECT l.*,d.username as driver_username,d.full_name as driver_name
                     FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id=d.id
                     WHERE l.company_id=%s ORDER BY l.pickup_date""", (company_id,))
    elif status:
        c.execute("""SELECT l.*,d.username as driver_username,d.full_name as driver_name
                     FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id=d.id
                     WHERE l.status=%s ORDER BY l.pickup_date""", (status,))
    else:
        c.execute("""SELECT l.*,d.username as driver_username,d.full_name as driver_name
                     FROM loads l LEFT JOIN drivers d ON l.assigned_driver_id=d.id
                     ORDER BY l.pickup_date""")
    loads = c.fetchall()
    conn.close()
    return [dict(l) for l in loads]

@app.post("/api/loads")
async def create_load(load: Load):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO loads (load_number,origin,destination,pickup_date,delivery_date,weight,miles,rate,load_type,commodity)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              (load.load_number,load.origin,load.destination,load.pickup_date,load.delivery_date,
               load.weight,load.miles,load.rate,load.load_type,load.commodity))
    load_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return {"id": load_id, "message": "Load created"}

@app.put("/api/loads/{load_id}")
async def update_load(load_id: int, load: Load):
    conn = get_db()
    c = conn.cursor()
    updates = load.dict(exclude_unset=True, exclude={'id'})
    if updates:
        fields = ", ".join([f"{k}=%s" for k in updates.keys()])
        c.execute(f"UPDATE loads SET {fields} WHERE id=%s", (*updates.values(), load_id))
        conn.commit()
    conn.close()
    return {"message": "Load updated"}

# ── ASSIGNMENTS ────────────────────────────────────────────────────────────

@app.get("/api/assignments")
async def get_assignments():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT a.*,d.username,d.full_name,d.status as driver_status,
                        l.load_number,l.origin,l.destination,l.rate,l.miles
                 FROM assignments a
                 JOIN drivers d ON a.driver_id=d.id
                 JOIN loads l ON a.load_id=l.id
                 ORDER BY a.assigned_at DESC""")
    assignments = c.fetchall()
    conn.close()
    return [dict(a) for a in assignments]

@app.post("/api/assignments")
async def create_assignment(assignment: Assignment):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    match_score = round(random.uniform(0.80,0.99),2)
    match_types = ["SOURCE LOAD","4 LOAD TOUR","1HR TO SOURCE","SOURCE TOUR"]
    match_type = assignment.match_type or random.choice(match_types)
    c.execute("""INSERT INTO assignments (driver_id,load_id,match_score,match_type)
                 VALUES (%s,%s,%s,%s) RETURNING id""",
              (assignment.driver_id,assignment.load_id,match_score,match_type))
    assignment_id = c.fetchone()["id"]
    c.execute("UPDATE drivers SET status='on_load' WHERE id=%s",(assignment.driver_id,))
    c.execute("UPDATE loads SET status='assigned',assigned_driver_id=%s WHERE id=%s",(assignment.driver_id,assignment.load_id))
    c.execute("SELECT * FROM loads WHERE id=%s",(assignment.load_id,))
    load = dict(c.fetchone())
    route_miles = load["miles"]
    c.execute("""INSERT INTO routes (assignment_id,total_miles,estimated_hours,fuel_cost,toll_cost)
                 VALUES (%s,%s,%s,%s,%s)""",
              (assignment_id,route_miles,round(route_miles/55,1),round(route_miles*0.43,2),round(route_miles*0.08,2)))
    # Auto-pull miles into IFTA from dispatch
    c.execute("SELECT full_name FROM drivers WHERE id=%s",(assignment.driver_id,))
    driver_row = c.fetchone()
    driver_name = driver_row["full_name"] if driver_row else "Unknown"
    # Get origin state from load
    origin_state = load.get("origin","").strip()[-2:].upper() if load.get("origin") else "XX"
    dest_state = load.get("destination","").strip()[-2:].upper() if load.get("destination") else "XX"
    trip_date = datetime.now().strftime("%Y-%m-%d")
    # Log origin state miles (half the trip)
    if origin_state in [s for s in ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"]]:
        c.execute("""INSERT INTO vehicle_miles (company_id,vehicle,driver_name,state,miles,trip_date,load_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  (load.get("company_id",1),f"TRK-{assignment.driver_id:03d}",driver_name,origin_state,round(route_miles*0.5,1),trip_date,load["id"]))
    # Log destination state miles (other half)
    if dest_state in [s for s in ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"]]:
        c.execute("""INSERT INTO vehicle_miles (company_id,vehicle,driver_name,state,miles,trip_date,load_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  (load.get("company_id",1),f"TRK-{assignment.driver_id:03d}",driver_name,dest_state,round(route_miles*0.5,1),trip_date,load["id"]))
    conn.commit()
    conn.close()
    return {"id":assignment_id,"match_score":match_score,"match_type":match_type}

# ── MATCH ENGINE ───────────────────────────────────────────────────────────

@app.post("/api/match")
async def match_drivers(request: MatchRequest):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM loads WHERE id=%s",(request.load_id,))
    load = dict(c.fetchone())
    c.execute("SELECT * FROM drivers WHERE status='available' ORDER BY on_time_rate DESC")
    available_drivers = [dict(d) for d in c.fetchall()]
    conn.close()
    match_types = ["SOURCE LOAD","4 LOAD TOUR","1HR TO SOURCE","SOURCE TOUR"]
    matches = []
    for i,d in enumerate(available_drivers[:5]):
        score = round(d["on_time_rate"]*random.uniform(0.88,1.0),2)
        matches.append({**d,"match_score":score,"match_type":match_types[i%len(match_types)],"eta_to_pickup":f"{random.randint(1,8)}h {random.randint(0,59)}m"})
    matches.sort(key=lambda x:x["match_score"],reverse=True)
    return {"load":load,"matches":matches}

# ── ROUTES ─────────────────────────────────────────────────────────────────

@app.get("/api/routes")
async def get_routes():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT r.*,a.match_type,a.status as assignment_status,
                        d.username,d.full_name,l.load_number,l.origin,l.destination
                 FROM routes r
                 JOIN assignments a ON r.assignment_id=a.id
                 JOIN drivers d ON a.driver_id=d.id
                 JOIN loads l ON a.load_id=l.id""")
    routes = c.fetchall()
    conn.close()
    return [dict(r) for r in routes]

ORS_API_KEY = os.environ.get("ORS_API_KEY")

def geocode_city(city: str):
    try:
        url = "https://api.openrouteservice.org/geocode/search"
        params = {"api_key": ORS_API_KEY, "text": city, "size": 1}
        r = http_requests.get(url, params=params, timeout=10)
        data = r.json()
        coords = data["features"][0]["geometry"]["coordinates"]
        return coords
    except:
        return None

def get_real_route(origin: str, destination: str):
    try:
        origin_coords = geocode_city(origin)
        dest_coords = geocode_city(destination)
        if not origin_coords or not dest_coords:
            return None
        url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
        headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
        body = {"coordinates": [origin_coords, dest_coords], "units": "mi"}
        r = http_requests.post(url, json=body, headers=headers, timeout=15)
        data = r.json()
        route = data["routes"][0]
        miles = round(route["summary"]["distance"], 1)
        hours = round(route["summary"]["duration"] / 3600, 1)
        return {"miles": miles, "hours": hours}
    except:
        return None

@app.post("/api/routes/optimize")
async def optimize_route(request: OptimizeRequest):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT r.*,l.origin,l.destination FROM routes r
                 JOIN assignments a ON r.assignment_id=a.id
                 JOIN loads l ON a.load_id=l.id
                 WHERE r.assignment_id=%s""", (request.assignment_id,))
    route = dict(c.fetchone())
    real = get_real_route(route["origin"], route["destination"])
    if real:
        new_miles = real["miles"]
        new_hours = real["hours"]
        new_fuel = round(new_miles * 0.43, 2)
        c.execute("UPDATE routes SET total_miles=%s,estimated_hours=%s,fuel_cost=%s WHERE assignment_id=%s",
                  (new_miles, new_hours, new_fuel, request.assignment_id))
        conn.commit()
        conn.close()
        return {"optimized": True, "real_route": True, "total_miles": new_miles,
                "estimated_hours": new_hours, "fuel_cost": new_fuel,
                "savings_miles": round(route["total_miles"] - new_miles, 1)}
    else:
        savings_pct = random.uniform(0.03, 0.08)
        new_miles = round(route["total_miles"] * (1 - savings_pct), 1)
        new_fuel = round(new_miles * 0.43, 2)
        c.execute("UPDATE routes SET total_miles=%s,estimated_hours=%s,fuel_cost=%s WHERE assignment_id=%s",
                  (new_miles, round(new_miles/55, 1), new_fuel, request.assignment_id))
        conn.commit()
        conn.close()
        return {"optimized": True, "real_route": False, "total_miles": new_miles,
                "savings_miles": round(route["total_miles"] - new_miles, 1)}

@app.get("/api/routes/distance")
async def get_distance(origin: str, destination: str):
    real = get_real_route(origin, destination)
    if real:
        return {"origin": origin, "destination": destination,
                "miles": real["miles"], "hours": real["hours"],
                "fuel_cost": round(real["miles"] * 0.43, 2), "real": True}
    return {"origin": origin, "destination": destination,
            "miles": None, "real": False, "error": "Could not calculate route"}


# ── ANALYTICS ──────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM drivers"); total_drivers = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM drivers WHERE status='available'"); available_drivers = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM loads WHERE status IN ('available','assigned','in_transit')"); active_loads = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(rate),0) FROM loads WHERE status='delivered'"); total_revenue = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM assignments WHERE status='active'"); active_assignments = c.fetchone()[0]
    c.execute("SELECT AVG(on_time_rate) FROM drivers"); avg_on_time = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(total_miles),0) FROM routes"); total_miles = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(fuel_cost),0) FROM routes"); fuel_cost = c.fetchone()[0]
    today = datetime.now()
    daily_trend = []
    for i in range(13,-1,-1):
        day = today - timedelta(days=i)
        daily_trend.append({"date":day.strftime("%m/%d"),"revenue":round(random.uniform(18000,42000),0),"loads":random.randint(4,14),"miles":random.randint(2000,6000)})
    c2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c2.execute("""SELECT driver_type,COUNT(*) as total,
                         SUM(CASE WHEN status='on_load' THEN 1 ELSE 0 END) as active
                  FROM drivers GROUP BY driver_type""")
    utilization = [dict(r) for r in c2.fetchall()]
    conn.close()
    return {
        "summary":{"total_drivers":total_drivers,"available_drivers":available_drivers,
                   "utilization_rate":round((total_drivers-available_drivers)/max(total_drivers,1)*100,1),
                   "active_loads":active_loads,"active_assignments":active_assignments,
                   "total_revenue":round(total_revenue,2),"avg_on_time_rate":round((avg_on_time or 0)*100,1),
                   "total_miles":round(total_miles,1),"total_fuel_cost":round(fuel_cost,2)},
        "daily_trend":daily_trend,"driver_utilization":utilization
    }

# ── COMPLIANCE ─────────────────────────────────────────────────────────────

@app.get("/api/compliance")
async def get_compliance():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT co.*,d.username,d.full_name,d.driver_type
                 FROM compliance co JOIN drivers d ON co.driver_id=d.id ORDER BY d.full_name""")
    records = [dict(r) for r in c.fetchall()]
    conn.close()
    for r in records:
        r["cdl_status"] = get_compliance_status(r["cdl_expiry"])
        r["medical_status"] = get_compliance_status(r["medical_card_expiry"])
        r["inspection_status"] = get_compliance_status(r["annual_inspection_expiry"])
        r["drug_test_status"] = get_compliance_status(r["drug_test_date"])
    return records

@app.post("/api/compliance")
async def create_compliance(record: ComplianceRecord):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO compliance (driver_id,cdl_expiry,medical_card_expiry,mvr_date,drug_test_date,annual_inspection_expiry,notes)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (driver_id) DO UPDATE SET
                 cdl_expiry=EXCLUDED.cdl_expiry,medical_card_expiry=EXCLUDED.medical_card_expiry,
                 mvr_date=EXCLUDED.mvr_date,drug_test_date=EXCLUDED.drug_test_date,
                 annual_inspection_expiry=EXCLUDED.annual_inspection_expiry,notes=EXCLUDED.notes""",
              (record.driver_id,record.cdl_expiry,record.medical_card_expiry,record.mvr_date,
               record.drug_test_date,record.annual_inspection_expiry,record.notes))
    conn.commit()
    conn.close()
    return {"message":"Compliance record saved"}

@app.get("/api/compliance/summary")
async def compliance_summary():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM compliance")
    records = [dict(r) for r in c.fetchall()]
    conn.close()
    total = len(records)
    expired = sum(1 for r in records if get_compliance_status(r["cdl_expiry"])=="expired" or get_compliance_status(r["medical_card_expiry"])=="expired")
    expiring = sum(1 for r in records if get_compliance_status(r["cdl_expiry"])=="expiring_soon" or get_compliance_status(r["medical_card_expiry"])=="expiring_soon")
    return {"total":total,"expired":expired,"expiring_soon":expiring,"compliant":total-expired-expiring}

# ── TRUCKPAY ───────────────────────────────────────────────────────────────

@app.get("/api/pay")
async def get_pay_records(driver_id: Optional[int] = None):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if driver_id:
        c.execute("""SELECT p.*,d.username,d.full_name,d.driver_type FROM pay_records p
                     JOIN drivers d ON p.driver_id=d.id WHERE p.driver_id=%s ORDER BY p.week_ending DESC""",(driver_id,))
    else:
        c.execute("""SELECT p.*,d.username,d.full_name,d.driver_type FROM pay_records p
                     JOIN drivers d ON p.driver_id=d.id ORDER BY p.week_ending DESC""")
    records = [dict(r) for r in c.fetchall()]
    conn.close()
    for r in records:
        r["total_deductions"] = r["fuel_deduction"]+r["insurance_deduction"]+r["advance_deduction"]+r["other_deduction"]
        r["net_pay"] = round(r["gross_pay"]-r["total_deductions"],2)
    return records

@app.post("/api/pay")
async def create_pay_record(record: PayRecord):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO pay_records (driver_id,load_id,week_ending,gross_pay,fuel_deduction,insurance_deduction,advance_deduction,other_deduction,notes)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (record.driver_id,record.load_id,record.week_ending,record.gross_pay,
               record.fuel_deduction,record.insurance_deduction,record.advance_deduction,record.other_deduction,record.notes))
    conn.commit()
    conn.close()
    return {"message":"Pay record created"}

@app.get("/api/pay/summary")
async def pay_summary():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM pay_records")
    records = [dict(r) for r in c.fetchall()]
    conn.close()
    total_gross = sum(r["gross_pay"] for r in records)
    total_deductions = sum(r["fuel_deduction"]+r["insurance_deduction"]+r["advance_deduction"]+r["other_deduction"] for r in records)
    return {"total_gross":round(total_gross,2),"total_deductions":round(total_deductions,2),"total_net":round(total_gross-total_deductions,2),"total_records":len(records)}

# ── INSURANCE ──────────────────────────────────────────────────────────────

@app.get("/api/insurance")
async def get_insurance():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM insurance_policies ORDER BY expiry_date ASC")
    policies = [dict(p) for p in c.fetchall()]
    conn.close()
    for p in policies:
        p["status"] = get_compliance_status(p["expiry_date"])
    return policies

@app.post("/api/insurance")
async def create_insurance(policy: InsurancePolicy):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO insurance_policies (truck_number,policy_number,provider,policy_type,premium,expiry_date,coverage_amount,notes)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
              (policy.truck_number,policy.policy_number,policy.provider,policy.policy_type,
               policy.premium,policy.expiry_date,policy.coverage_amount,policy.notes))
    conn.commit()
    conn.close()
    return {"message":"Insurance policy added"}

@app.get("/api/insurance/summary")
async def insurance_summary():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM insurance_policies")
    policies = [dict(p) for p in c.fetchall()]
    conn.close()
    total = len(policies)
    expired = sum(1 for p in policies if get_compliance_status(p["expiry_date"])=="expired")
    expiring = sum(1 for p in policies if get_compliance_status(p["expiry_date"])=="expiring_soon")
    total_premium = sum(p["premium"] for p in policies)
    return {"total":total,"expired":expired,"expiring_soon":expiring,"compliant":total-expired-expiring,"total_premium":round(total_premium,2)}

# ── AUTH ───────────────────────────────────────────────────────────────────

@app.post("/api/auth/signup")
async def company_signup(data: CompanySignup):
    conn = get_db()
    c = conn.cursor()
    try:
        trial_ends = datetime.now() + timedelta(days=14)
        c.execute("INSERT INTO companies (company_name,dot_number,email,trial_ends_at,is_subscribed) VALUES (%s,%s,%s,%s,0) RETURNING id",
                  (data.company_name,data.dot_number,data.email,trial_ends))
        company_id = c.fetchone()[0]
        c.execute("INSERT INTO users (company_id,full_name,email,password_hash,role) VALUES (%s,%s,%s,%s,'manager') RETURNING id",
                  (company_id,data.full_name,data.email,hash_password(data.password)))
        user_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        return {"message":"Account created","user_id":user_id,"company_id":company_id,"role":"manager","full_name":data.full_name,"company_name":data.company_name}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400,detail="Email already registered")

@app.post("/api/auth/login")
async def login(data: UserLogin):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT u.*,co.company_name FROM users u JOIN companies co ON u.company_id=co.id
                 WHERE u.email=%s AND u.password_hash=%s""",(data.email,hash_password(data.password)))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401,detail="Invalid email or password")
    user = dict(user)
    return {"user_id":user["id"],"company_id":user["company_id"],"full_name":user["full_name"],
            "email":user["email"],"role":user["role"],"company_name":user["company_name"]}

@app.post("/api/auth/invite")
async def invite_driver(data: InviteDriver):
    conn = get_db()
    c = conn.cursor()
    token = secrets.token_urlsafe(32)
    try:
        c.execute("""INSERT INTO users (company_id,full_name,email,password_hash,role,invite_token,is_active)
                     VALUES (%s,%s,%s,%s,'driver',%s,0)""",
                  (data.company_id,data.full_name,data.email,"",token))
        conn.commit()
        conn.close()
        invite_link = f"https://www.freightquik.com/auth.html?token={token}&email={data.email}"
        send_email(
            to=data.email,
            subject=f"You've been invited to join FreightQuick",
            html=invite_email_html(data.full_name, invite_link, "Your Fleet")
        )
        return {"message":"Driver invited","invite_token":token,"invite_link":invite_link}
    except:
        conn.close()
        raise HTTPException(status_code=400,detail="Email already exists")
    
class AcceptInvite(BaseModel):
    token: str
    email: str
    full_name: str
    password: str  

@app.post("/api/auth/accept-invite")
async def accept_invite(data: AcceptInvite):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM users WHERE invite_token=%s AND email=%s", (data.token, data.email))
    user = c.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired invite link")
    user = dict(user)
    c.execute("UPDATE users SET password_hash=%s, full_name=%s, is_active=1, invite_token=NULL WHERE id=%s",
              (hash_password(data.password), data.full_name, user["id"]))
    c.execute("SELECT co.company_name FROM companies co WHERE co.id=%s", (user["company_id"],))
    company = c.fetchone()
    conn.commit()
    conn.close()
    return {"user_id": user["id"], "company_id": user["company_id"], "full_name": data.full_name,
            "email": data.email, "role": user["role"], "company_name": company["company_name"]}


@app.post("/api/auth/make-superadmin")
async def make_superadmin(data: dict):
    secret = data.get("secret")
    email = data.get("email")
    if secret != "FREIGHTQUICK-SUPER-2026":
        raise HTTPException(status_code=403,detail="Invalid secret")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET role='superadmin' WHERE email=%s",(email,))
    conn.commit()
    conn.close()
    return {"message":"Superadmin role granted"}

class DamageAlert(BaseModel):
    company_id: int
    driver_name: str
    vehicle: str
    issues: list

@app.post("/api/inspection/damage-alert")
async def damage_alert(data: DamageAlert):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT u.email,co.company_name FROM users u JOIN companies co ON u.company_id=co.id WHERE u.company_id=%s AND u.role='manager'", (data.company_id,))
    managers = c.fetchall()
    conn.close()
    for m in managers:
        send_email(
            to=m["email"],
            subject=f"⚠ Damage Alert — {data.vehicle}",
            html=damage_alert_email_html(data.driver_name, data.vehicle, data.issues, m["company_name"])
        )
    return {"message": "Alert sent"}

# ── SUPERADMIN ─────────────────────────────────────────────────────────────

@app.get("/api/superadmin/companies")
async def get_all_companies():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT co.*,COUNT(u.id) as total_users,
                        SUM(CASE WHEN u.role='manager' THEN 1 ELSE 0 END) as managers,
                        SUM(CASE WHEN u.role='driver' THEN 1 ELSE 0 END) as drivers
                 FROM companies co LEFT JOIN users u ON co.id=u.company_id
                 GROUP BY co.id ORDER BY co.created_at DESC""")
    companies = [dict(r) for r in c.fetchall()]
    conn.close()
    return companies

# ── EMAIL NOTIFICATIONS ────────────────────────────────────────────────────

def send_email(to: str, subject: str, html: str):
    try:
        resend.Emails.send({
            "from": "FreightQuick <notifications@freightquick.app>",
            "to": to,
            "subject": subject,
            "html": html
        })
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def invite_email_html(full_name: str, invite_link: str, company_name: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0D0D0D;color:#E8E0D0;padding:0;border-radius:12px;overflow:hidden">
      <div style="background:#FF6B35;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">⚡ FreightQuick</h1>
        <p style="color:#fff;margin:8px 0 0;opacity:0.9">Fleet Management Platform</p>
      </div>
      <div style="padding:32px">
        <h2 style="color:#F5F0E8;margin:0 0 16px">You've been invited!</h2>
        <p style="color:#9CA3AF;line-height:1.6">Hi {full_name},</p>
        <p style="color:#9CA3AF;line-height:1.6"><strong style="color:#F5F0E8">{company_name}</strong> has invited you to join FreightQuick as a driver.</p>
        <div style="text-align:center;margin:32px 0">
          <a href="{invite_link}" style="background:#FF6B35;color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px">Activate Your Account →</a>
        </div>
        <p style="color:#6B7280;font-size:12px;line-height:1.6">This link will expire in 7 days. If you did not expect this invitation please ignore this email.</p>
      </div>
      <div style="background:#161616;padding:16px;text-align:center">
        <p style="color:#6B7280;font-size:11px;margin:0">FreightQuick — Fleet Management Platform</p>
      </div>
    </div>
    """

def damage_alert_email_html(driver_name: str, vehicle: str, issues: list, company_name: str) -> str:
    issues_html = "".join([f"<li style='color:#F87171;margin-bottom:4px'>⚠ {issue}</li>" for issue in issues])
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0D0D0D;color:#E8E0D0;padding:0;border-radius:12px;overflow:hidden">
      <div style="background:#DC2626;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">⚠ Damage Alert</h1>
        <p style="color:#fff;margin:8px 0 0;opacity:0.9">Vehicle inspection found issues</p>
      </div>
      <div style="padding:32px">
        <p style="color:#9CA3AF;line-height:1.6">A vehicle inspection submitted by <strong style="color:#F5F0E8">{driver_name}</strong> has reported damage on <strong style="color:#F5F0E8">{vehicle}</strong>.</p>
        <div style="background:#1a0707;border:1px solid #450a0a;border-radius:8px;padding:16px;margin:20px 0">
          <p style="color:#F87171;font-weight:700;margin:0 0 10px">Damaged Items:</p>
          <ul style="margin:0;padding-left:20px">{issues_html}</ul>
        </div>
        <p style="color:#9CA3AF;font-size:13px">Please review the inspection report and take appropriate action.</p>
      </div>
      <div style="background:#161616;padding:16px;text-align:center">
        <p style="color:#6B7280;font-size:11px;margin:0">{company_name} — Powered by FreightQuick</p>
      </div>
    </div>
    """

def trial_ending_email_html(company_name: str, days_left: int) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0D0D0D;color:#E8E0D0;padding:0;border-radius:12px;overflow:hidden">
      <div style="background:#FF6B35;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">⚡ FreightQuick</h1>
      </div>
      <div style="padding:32px">
        <h2 style="color:#F5F0E8;margin:0 0 16px">Your trial ends in {days_left} days</h2>
        <p style="color:#9CA3AF;line-height:1.6">Hi {company_name},</p>
        <p style="color:#9CA3AF;line-height:1.6">Your 14-day free trial ends in <strong style="color:#FF6B35">{days_left} days</strong>. Subscribe now to keep access to all your fleet data.</p>
        <div style="text-align:center;margin:32px 0">
          <a href="https://freightquick-ap.onrender.com/app.html" style="background:#FF6B35;color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px">Subscribe Now →</a>
        </div>
        <p style="color:#6B7280;font-size:12px">Plans start at $29/driver/month. Cancel anytime.</p>
      </div>
      <div style="background:#161616;padding:16px;text-align:center">
        <p style="color:#6B7280;font-size:11px;margin:0">FreightQuick — Fleet Management Platform</p>
      </div>
    </div>
    """

# ── STRIPE PAYMENTS ────────────────────────────────────────────────────────

class CreateCheckout(BaseModel):
    company_id: int
    company_name: str
    email: str
    driver_count: int

@app.post("/api/stripe/create-checkout")
async def create_checkout(data: CreateCheckout):
    try:
        import stripe as stripe_lib
        stripe_lib.api_key = os.environ.get("STRIPE_SECRET_KEY")
        session = stripe_lib.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer_email=data.email,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": 2900,
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": "FreightQuick — Driver Subscription",
                        "description": f"Fleet management for {data.company_name}",
                    },
                },
                "quantity": data.driver_count,
            }],
            metadata={
                "company_id": str(data.company_id),
                "company_name": data.company_name,
            },
            success_url="https://freightquick-ap.onrender.com/app.html?payment=success",
            cancel_url="https://freightquick-ap.onrender.com/app.html?payment=cancelled",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/stripe/plans")
async def get_plans():
    return {
        "plans": [
            {"name":"Starter","drivers":5,"price":145,"per_driver":29,"description":"Up to 5 drivers"},
            {"name":"Growth","drivers":15,"price":435,"per_driver":29,"description":"Up to 15 drivers"},
            {"name":"Fleet","drivers":50,"price":1450,"per_driver":29,"description":"Up to 50 drivers"},
        ]
    }
@app.get("/api/debug/stripe")
async def debug_stripe():
    key = os.environ.get("STRIPE_SECRET_KEY")
    return {"key_exists": key is not None, "key_prefix": key[:10] if key else None}

@app.get("/api/trial/status/{company_id}")
async def trial_status(company_id: int):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT trial_ends_at, is_subscribed FROM companies WHERE id=%s", (company_id,))
    company = c.fetchone()
    conn.close()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company = dict(company)
    trial_ends = company["trial_ends_at"]
    is_subscribed = company["is_subscribed"]
    if is_subscribed:
        return {"status": "subscribed", "days_left": None}
    if trial_ends:
        days_left = (trial_ends - datetime.now()).days
        if days_left > 0:
            return {"status": "trial", "days_left": days_left}
        else:
            return {"status": "expired", "days_left": 0}
    return {"status": "trial", "days_left": 14}

# ── INSPECTIONS ────────────────────────────────────────────────────────────

class InspectionRecord(BaseModel):
    company_id: int
    driver_name: str
    vehicle: str
    status: str
    damage_items: Optional[str] = None
    gps_location: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/inspections")
async def save_inspection(data: InspectionRecord):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""INSERT INTO inspections (company_id,driver_name,vehicle,status,damage_items,gps_location,notes)
                 VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              (data.company_id,data.driver_name,data.vehicle,data.status,
               data.damage_items,data.gps_location,data.notes))
    result = c.fetchone()
    conn.commit()
    conn.close()
    return {"id": result["id"], "message": "Inspection saved"}

@app.get("/api/inspections")
async def get_inspections(company_id: int = 1):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM inspections WHERE company_id=%s ORDER BY submitted_at DESC", (company_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ── FUEL & IFTA ────────────────────────────────────────────────────────────

IFTA_RATES = {
    "AL":0.290,"AK":0.080,"AZ":0.260,"AR":0.285,"CA":0.823,"CO":0.205,
    "CT":0.402,"DE":0.220,"FL":0.337,"GA":0.312,"ID":0.320,"IL":0.455,
    "IN":0.530,"IA":0.325,"KS":0.260,"KY":0.246,"LA":0.200,"ME":0.312,
    "MD":0.373,"MA":0.240,"MI":0.263,"MN":0.285,"MS":0.180,"MO":0.170,
    "MT":0.290,"NE":0.246,"NV":0.270,"NH":0.222,"NJ":0.418,"NM":0.210,
    "NY":0.474,"NC":0.362,"ND":0.230,"OH":0.385,"OK":0.190,"OR":0.360,
    "PA":0.576,"RI":0.340,"SC":0.260,"SD":0.280,"TN":0.270,"TX":0.200,
    "UT":0.245,"VT":0.270,"VA":0.262,"WA":0.494,"WV":0.357,"WI":0.329,
    "WY":0.240
}

class FuelEntry(BaseModel):
    company_id: int
    driver_name: str
    vehicle: str
    state: str
    gallons: float
    price_per_gallon: float
    odometer: Optional[int] = None
    fuel_date: str
    fuel_type: str = "diesel"
    vendor: Optional[str] = None
    notes: Optional[str] = None

class MilesEntry(BaseModel):
    company_id: int
    vehicle: str
    driver_name: str
    state: str
    miles: float
    trip_date: str
    load_id: Optional[int] = None

@app.post("/api/fuel")
async def add_fuel(data: FuelEntry):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    total = round(data.gallons * data.price_per_gallon, 2)
    c.execute("""INSERT INTO fuel_entries (company_id,driver_name,vehicle,state,gallons,price_per_gallon,total_cost,odometer,fuel_date,fuel_type,vendor,notes)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              (data.company_id,data.driver_name,data.vehicle,data.state,data.gallons,
               data.price_per_gallon,total,data.odometer,data.fuel_date,data.fuel_type,data.vendor,data.notes))
    result = c.fetchone()
    conn.commit()
    conn.close()
    return {"id": result["id"], "total_cost": total, "message": "Fuel entry saved"}

@app.get("/api/fuel")
async def get_fuel(company_id: int = 1):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM fuel_entries WHERE company_id=%s ORDER BY fuel_date DESC", (company_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@app.post("/api/miles")
async def add_miles(data: MilesEntry):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""INSERT INTO vehicle_miles (company_id,vehicle,driver_name,state,miles,trip_date,load_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              (data.company_id,data.vehicle,data.driver_name,data.state,data.miles,data.trip_date,data.load_id))
    conn.commit()
    conn.close()
    return {"message": "Miles recorded"}

@app.get("/api/ifta/report")
async def ifta_report(company_id: int = 1, quarter: int = 1, year: int = 2026):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Quarter date ranges
    quarters = {1:("01-01","03-31"),2:("04-01","06-30"),3:("07-01","09-30"),4:("10-01","12-31")}
    start, end = quarters[quarter]
    start_date = f"{year}-{start}"
    end_date = f"{year}-{end}"
    # Get miles by state
    c.execute("""SELECT state, SUM(miles) as total_miles FROM vehicle_miles
                 WHERE company_id=%s AND trip_date BETWEEN %s AND %s GROUP BY state""",
              (company_id, start_date, end_date))
    miles_by_state = {r["state"]: float(r["total_miles"]) for r in c.fetchall()}
    # Get fuel by state
    c.execute("""SELECT state, SUM(gallons) as total_gallons, SUM(total_cost) as total_cost
                 FROM fuel_entries WHERE company_id=%s AND fuel_date BETWEEN %s AND %s GROUP BY state""",
              (company_id, start_date, end_date))
    fuel_by_state = {r["state"]: {"gallons": float(r["total_gallons"]), "cost": float(r["total_cost"])} for r in c.fetchall()}
    # Totals
    total_miles = sum(miles_by_state.values())
    total_gallons = sum(f["gallons"] for f in fuel_by_state.values())
    fleet_mpg = round(total_miles / total_gallons, 2) if total_gallons > 0 else 0
    # IFTA calculation per state
    jurisdictions = []
    for state in set(list(miles_by_state.keys()) + list(fuel_by_state.keys())):
        miles = miles_by_state.get(state, 0)
        gallons_purchased = fuel_by_state.get(state, {}).get("gallons", 0)
        rate = IFTA_RATES.get(state, 0.25)
        gallons_consumed = round(miles / fleet_mpg, 3) if fleet_mpg > 0 else 0
        tax_due = round((gallons_consumed - gallons_purchased) * rate, 2)
        jurisdictions.append({
            "state": state,
            "miles": round(miles, 1),
            "gallons_purchased": round(gallons_purchased, 3),
            "gallons_consumed": round(gallons_consumed, 3),
            "tax_rate": rate,
            "tax_due": tax_due,
            "status": "DUE" if tax_due > 0 else "CREDIT"
        })
    jurisdictions.sort(key=lambda x: x["state"])
    total_tax = round(sum(j["tax_due"] for j in jurisdictions), 2)
    conn.close()
    return {
        "quarter": quarter, "year": year,
        "total_miles": round(total_miles, 1),
        "total_gallons": round(total_gallons, 3),
        "fleet_mpg": fleet_mpg,
        "total_tax_due": total_tax,
        "jurisdictions": jurisdictions
    }

@app.get("/api/fuel/analytics")
async def fuel_analytics(company_id: int = 1):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT vehicle, 
                 SUM(gallons) as total_gallons,
                 SUM(total_cost) as total_cost,
                 AVG(price_per_gallon) as avg_ppg,
                 COUNT(*) as fill_ups
                 FROM fuel_entries WHERE company_id=%s GROUP BY vehicle""", (company_id,))
    by_vehicle = [dict(r) for r in c.fetchall()]
    c.execute("""SELECT state, SUM(total_cost) as spend FROM fuel_entries
                 WHERE company_id=%s GROUP BY state ORDER BY spend DESC LIMIT 10""", (company_id,))
    by_state = [dict(r) for r in c.fetchall()]
    c.execute("""SELECT SUM(total_cost) as total_spend, SUM(gallons) as total_gallons,
                 AVG(price_per_gallon) as avg_ppg FROM fuel_entries WHERE company_id=%s""", (company_id,))
    totals = dict(c.fetchone())
    conn.close()
    return {"by_vehicle": by_vehicle, "by_state": by_state, "totals": totals}

@app.get("/api/ifta/export")
async def ifta_export(company_id: int = 1, quarter: int = 1, year: int = 2026):
    from fastapi.responses import StreamingResponse
    import io, csv
    quarters = {1:("01-01","03-31"),2:("04-01","06-30"),3:("07-01","09-30"),4:("10-01","12-31")}
    start, end = quarters[quarter]
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""SELECT state, SUM(miles) as total_miles FROM vehicle_miles
                 WHERE company_id=%s AND trip_date BETWEEN %s AND %s GROUP BY state""",
              (company_id, f"{year}-{start}", f"{year}-{end}"))
    miles_by_state = {r["state"]: float(r["total_miles"]) for r in c.fetchall()}
    c.execute("""SELECT state, SUM(gallons) as total_gallons FROM fuel_entries
                 WHERE company_id=%s AND fuel_date BETWEEN %s AND %s GROUP BY state""",
              (company_id, f"{year}-{start}", f"{year}-{end}"))
    fuel_by_state = {r["state"]: float(r["total_gallons"]) for r in c.fetchall()}
    conn.close()
    total_miles = sum(miles_by_state.values())
    total_gallons = sum(fuel_by_state.values())
    fleet_mpg = total_miles / total_gallons if total_gallons > 0 else 0
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"IFTA Report Q{quarter} {year}"])
    writer.writerow([f"Total Miles: {round(total_miles,1)}", f"Total Gallons: {round(total_gallons,3)}", f"Fleet MPG: {round(fleet_mpg,2)}"])
    writer.writerow([])
    writer.writerow(["State","Miles","Gal Purchased","Gal Consumed","Tax Rate","Tax Due/Credit","Status"])
    for state in sorted(set(list(miles_by_state.keys())+list(fuel_by_state.keys()))):
        miles = miles_by_state.get(state,0)
        gallons_purchased = fuel_by_state.get(state,0)
        rate = IFTA_RATES.get(state,0.25)
        gallons_consumed = round(miles/fleet_mpg,3) if fleet_mpg > 0 else 0
        tax_due = round((gallons_consumed-gallons_purchased)*rate,2)
        writer.writerow([state,round(miles,1),round(gallons_purchased,3),gallons_consumed,rate,tax_due,"DUE" if tax_due>0 else "CREDIT"])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":f"attachment; filename=IFTA_Q{quarter}_{year}.csv"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
