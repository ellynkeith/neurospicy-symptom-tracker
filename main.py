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

# Taxonomy retired 2026-09-09: it was autism-coded (sensory processing,
# stimming, shutdown), which doesn't match this kid's actual evaluated
# profile (ADHD + ODD; specifically assessed for and ruled out for ASD).
# Kept here only so migrate_category_taxonomy() knows exactly which rows to
# remove from an existing deployment's `categories` table -- never inserted.
RETIRED_DEFAULT_CATEGORIES = [
    "meltdown",
    "shutdown",
    "sensory seeking",
    "sensory avoidance",
    "stimming",
    "anxiety",
    "rigidity",
    "aggression",
]

# DSM-5 ODD's three symptom clusters (angry/irritable mood,
# argumentative/defiant behavior, vindictiveness) plus the three ADHD
# presentations (impulsive, inattentive, hyperactive/restless).
DEFAULT_CATEGORIES = [
    "angry/irritable",
    "argumentative/defiant",
    "vindictive",
    "impulsive",
    "inattentive",
    "hyperactive/restless",
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
                days_ago=0, entry_time="16:45", categories=["angry/irritable", "argumentative/defiant"], setting="home",
                duration_minutes=20, intensity=4, trigger="told no to more screen time",
                notes="Yelling and refusing to hand over the tablet. Took about 20 min to de-escalate.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=0, entry_time="08:15", categories=["inattentive"], setting="school",
                duration_minutes=5, intensity=2, trigger="multi-step morning instructions",
                notes="Lost track partway through getting backpack ready, needed a re-prompt.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=1, entry_time="18:30", categories=["hyperactive/restless"], setting="home",
                duration_minutes=None, intensity=1, trigger=None,
                notes="Couldn't stay seated through dinner, up and down repeatedly. Low-stakes, just noting the pattern.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=1, entry_time="07:50", categories=["impulsive"], setting="transitions",
                duration_minutes=10, intensity=3, trigger="asked to wait for breakfast",
                notes="Grabbed food off a sibling's plate without asking, no warning first.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=2, entry_time="13:10", categories=["argumentative/defiant"], setting="public",
                duration_minutes=15, intensity=3, trigger="asked to leave the playground",
                notes="Refused, argued about the rule itself rather than just not wanting to leave.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=3, entry_time="15:00", categories=["hyperactive/restless", "impulsive"], setting="home",
                duration_minutes=30, intensity=1, trigger=None,
                notes="High energy the whole afternoon, jumping between activities without finishing any.",
                logged_by="Demo Babysitter",
            ),
            dict(
                days_ago=4, entry_time="09:20", categories=["inattentive"], setting="school",
                duration_minutes=25, intensity=2, trigger="independent seatwork",
                notes="Drifted off task repeatedly, needed several redirects to finish the worksheet.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=5, entry_time="17:40", categories=["vindictive"], setting="home",
                duration_minutes=8, intensity=3, trigger="sibling was allowed to pick the show",
                notes="Deliberately broke a piece of the sibling's toy afterward, said it was on purpose.",
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
    migrate_category_taxonomy(conn=None)


def migrate_category_taxonomy(conn=None):
    """Remove the old autism-coded default categories (see
    RETIRED_DEFAULT_CATEGORIES) from an existing deployment's `categories`
    table. Only ever deletes those specific, known-retired names -- any
    category the user added herself is left untouched. Existing entries
    already tagged with a retired category keep that tag; it just won't
    appear as a suggested chip or filter option going forward. Safe to run
    on every startup: a no-op once the retired rows are gone.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM categories WHERE name = ANY(%s)",
                (RETIRED_DEFAULT_CATEGORIES,),
            )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


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
