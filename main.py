import base64
import hmac
import itertools
import os
import threading
from contextlib import contextmanager
from datetime import date, time, timedelta
from typing import List, Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

DATABASE_URL = os.environ.get("DATABASE_URL")

# Shared household login. Set APP_PASSWORD in the environment to turn this on;
# APP_USERNAME defaults to "family" if not set. This is deliberately simple
# (one shared login, browser's native basic-auth prompt) -- it's meant to keep
# the app off of casual/accidental access, not to withstand a targeted attack.
APP_USERNAME = os.environ.get("APP_USERNAME", "family")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

# Optional second login for letting someone click around without seeing real
# data. Demo requests never touch Postgres -- they're served entirely out of
# the in-memory DemoStore below, which resets on every server restart. If
# DEMO_PASSWORD isn't set, the demo login is simply disabled.
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD")

# Paths that should stay reachable without logging in, e.g. so Render's own
# health checks don't get blocked by auth and mark the service unhealthy.
PUBLIC_PATHS = {"/api/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        if not APP_PASSWORD:
            # Fail closed with a clear message rather than silently running
            # the app wide open if someone forgets to set the password.
            return Response(
                "Server misconfigured: APP_PASSWORD is not set.",
                status_code=500,
            )

        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
            except Exception:
                username, password = "", ""

            if hmac.compare_digest(username, APP_USERNAME) and hmac.compare_digest(
                password, APP_PASSWORD
            ):
                request.state.demo = False
                return await call_next(request)

            if (
                DEMO_PASSWORD
                and hmac.compare_digest(username, DEMO_USERNAME)
                and hmac.compare_digest(password, DEMO_PASSWORD)
            ):
                request.state.demo = True
                return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Behavior Tracker"'},
        )


app = FastAPI()

app.add_middleware(BasicAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_CATEGORIES = [
    "meltdown",
    "shutdown",
    "sensory seeking",
    "sensory avoidance",
    "stimming",
    "anxiety",
    "rigidity",
    "aggression",
]


def is_demo(request: Request) -> bool:
    return getattr(request.state, "demo", False)


# ---------------------------------------------------------------------------
# Demo mode: an in-memory store so a demo visitor can fully click around --
# add, filter, delete -- without ever reading or writing the real database.
# Shared across all demo visitors (not per-session) and resets to the seed
# data below on every server restart.
# ---------------------------------------------------------------------------
class DemoStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._id_counter = itertools.count(1)
        self.categories = list(DEFAULT_CATEGORIES)
        self.entries = []
        self._seed()

    def _next_id(self):
        return next(self._id_counter)

    def _seed(self):
        today = date.today()
        seed_rows = [
            dict(
                days_ago=0, entry_time="16:45", categories=["meltdown", "aggression"], setting="home",
                duration_minutes=20, intensity=4, trigger="transition from screen time",
                notes="Took about 20 min to settle. Dimming the lights helped.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=0, entry_time="08:15", categories=["sensory avoidance"], setting="school",
                duration_minutes=5, intensity=2, trigger="loud cafeteria",
                notes="Asked for noise-canceling headphones, worked well.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=1, entry_time="18:30", categories=["stimming"], setting="home",
                duration_minutes=None, intensity=1, trigger=None,
                notes="Hand-flapping during favorite show, seemed happy/regulated.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=1, entry_time="07:50", categories=["rigidity", "anxiety"], setting="transitions",
                duration_minutes=10, intensity=3, trigger="unexpected change in morning routine",
                notes="Wanted the usual breakfast order, got upset when we were out of the usual cereal.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=2, entry_time="13:10", categories=["anxiety"], setting="public",
                duration_minutes=15, intensity=3, trigger="crowded store",
                notes="Asked to leave, felt better once we were back in the car.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=3, entry_time="15:00", categories=["sensory seeking"], setting="home",
                duration_minutes=30, intensity=1, trigger=None,
                notes="Long stretch of jumping on the trampoline, very regulated afterward.",
                logged_by="Demo Babysitter",
            ),
            dict(
                days_ago=4, entry_time="09:20", categories=["shutdown"], setting="school",
                duration_minutes=25, intensity=4, trigger="fire drill",
                notes="Went quiet and unresponsive for a while, recovered with a quiet break.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=5, entry_time="17:40", categories=["aggression"], setting="home",
                duration_minutes=8, intensity=3, trigger="sibling took a toy",
                notes="Brief, resolved with a reset in another room.",
                logged_by="Demo Parent",
            ),
        ]
        for row in seed_rows:
            entry_date = today - timedelta(days=row["days_ago"])
            self.entries.append(
                {
                    "id": self._next_id(),
                    "entry_date": entry_date.isoformat(),
                    "entry_time": row["entry_time"],
                    "categories": row["categories"],
                    "setting": row["setting"],
                    "duration_minutes": row["duration_minutes"],
                    "intensity": row["intensity"],
                    "trigger": row["trigger"],
                    "notes": row["notes"],
                    "logged_by": row["logged_by"],
                }
            )

    def list_entries(self):
        with self._lock:
            return sorted(
                self.entries,
                key=lambda e: (e["entry_date"], e["entry_time"] or "", e["id"]),
                reverse=True,
            )

    def create_entry(self, entry: "EntryIn"):
        with self._lock:
            row = {
                "id": self._next_id(),
                "entry_date": entry.entry_date.isoformat(),
                "entry_time": entry.entry_time.isoformat() if entry.entry_time else None,
                "categories": entry.categories,
                "setting": entry.setting,
                "duration_minutes": entry.duration_minutes,
                "intensity": entry.intensity,
                "trigger": entry.trigger,
                "notes": entry.notes,
                "logged_by": entry.logged_by,
            }
            self.entries.append(row)
            return row

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            before = len(self.entries)
            self.entries = [e for e in self.entries if e["id"] != entry_id]
            return len(self.entries) != before

    def list_categories(self):
        with self._lock:
            return sorted(self.categories)

    def create_category(self, name: str):
        with self._lock:
            if name not in self.categories:
                self.categories.append(name)


demo_store = DemoStore()


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not set")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    if not DATABASE_URL:
        # Allow the app to boot even without a DB configured yet (e.g. first
        # Render deploy before DATABASE_URL is set), rather than crash-looping.
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id SERIAL PRIMARY KEY,
                    entry_date DATE NOT NULL,
                    entry_time TIME,
                    categories TEXT[] NOT NULL DEFAULT '{}',
                    setting TEXT,
                    duration_minutes INTEGER,
                    intensity INTEGER,
                    trigger TEXT,
                    notes TEXT,
                    logged_by TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            for cat in DEFAULT_CATEGORIES:
                cur.execute(
                    "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    (cat,),
                )
        conn.commit()
    migrate_single_category_column(conn=None)


def migrate_single_category_column(conn=None):
    """Migrate an older deployment's singular `category TEXT` column to the
    current `categories TEXT[]` column, preserving existing data. Safe to run
    on every startup: each step is a no-op once the migration has happened.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'entries' AND column_name = 'category'
                """
            )
            has_old_column = cur.fetchone() is not None

            if has_old_column:
                cur.execute(
                    """
                    ALTER TABLE entries
                    ADD COLUMN IF NOT EXISTS categories TEXT[] NOT NULL DEFAULT '{}'
                    """
                )
                cur.execute(
                    """
                    UPDATE entries
                    SET categories = ARRAY[category]
                    WHERE category IS NOT NULL
                      AND (categories IS NULL OR categories = '{}')
                    """
                )
                cur.execute("ALTER TABLE entries DROP COLUMN category")
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


@app.on_event("startup")
def on_startup():
    init_db()


class EntryIn(BaseModel):
    entry_date: date
    entry_time: Optional[time] = None
    categories: List[str]
    setting: Optional[str] = None
    duration_minutes: Optional[int] = None
    intensity: Optional[int] = None
    trigger: Optional[str] = None
    notes: Optional[str] = None
    logged_by: Optional[str] = None

    @field_validator("categories")
    @classmethod
    def categories_not_empty(cls, value: List[str]) -> List[str]:
        cleaned = [c.strip().lower() for c in value if c and c.strip()]
        # de-dupe while preserving order
        seen = set()
        deduped = []
        for c in cleaned:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        if not deduped:
            raise ValueError("At least one category is required")
        return deduped


class CategoryIn(BaseModel):
    name: str


@app.get("/api/health")
def health():
    return {"status": "ok", "db_configured": bool(DATABASE_URL)}


@app.get("/api/whoami")
def whoami(request: Request):
    return {"demo": is_demo(request)}


@app.get("/api/entries")
def list_entries(request: Request):
    if is_demo(request):
        return demo_store.list_entries()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM entries "
                "ORDER BY entry_date DESC, entry_time DESC NULLS LAST, id DESC"
            )
            rows = cur.fetchall()
    return rows


@app.post("/api/entries")
def create_entry(entry: EntryIn, request: Request):
    if is_demo(request):
        return demo_store.create_entry(entry)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO entries
                    (entry_date, entry_time, categories, setting, duration_minutes,
                     intensity, trigger, notes, logged_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    entry.entry_date,
                    entry.entry_time,
                    entry.categories,
                    entry.setting,
                    entry.duration_minutes,
                    entry.intensity,
                    entry.trigger,
                    entry.notes,
                    entry.logged_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int, request: Request):
    if is_demo(request):
        if not demo_store.delete_entry(entry_id):
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"deleted": entry_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
            deleted = cur.rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"deleted": entry_id}


@app.get("/api/categories")
def list_categories(request: Request):
    if is_demo(request):
        return demo_store.list_categories()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM categories ORDER BY name")
            rows = cur.fetchall()
    return [r[0] for r in rows]


@app.post("/api/categories")
def create_category(category: CategoryIn, request: Request):
    name = category.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    if is_demo(request):
        demo_store.create_category(name)
        return {"name": name}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                (name,),
            )
        conn.commit()
    return {"name": name}


# Serve the frontend last so it doesn't shadow the /api routes above.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
