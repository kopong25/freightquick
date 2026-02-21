from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import random
import os
import hashlib
import secrets
import stripe
STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY")
stripe.api_key = STRIPE_KEY

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

@app.post("/api/routes/optimize")
async def optimize_route(request: OptimizeRequest):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM routes WHERE assignment_id=%s",(request.assignment_id,))
    route = dict(c.fetchone())
    savings_pct = random.uniform(0.03,0.08)
    new_miles = round(route["total_miles"]*(1-savings_pct),1)
    new_fuel = round(new_miles*0.43,2)
    c.execute("UPDATE routes SET total_miles=%s,estimated_hours=%s,fuel_cost=%s WHERE assignment_id=%s",
              (new_miles,round(new_miles/55,1),new_fuel,request.assignment_id))
    conn.commit()
    conn.close()
    return {"optimized":True,"savings_miles":round(route["total_miles"]-new_miles,1),"new_total":new_miles}

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
        return {"message":"Driver invited","invite_token":token}
    except:
        conn.close()
        raise HTTPException(status_code=400,detail="Email already exists")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
