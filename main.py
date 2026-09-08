import base64
import hmac
import os
from contextlib import contextmanager
from datetime import date, time
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

DATABASE_URL = os.environ.get("DATABASE_URL")

# Shared household login. Set APP_PASSWORD in the environment to turn this on;
# APP_USERNAME defaults to "family" if not set. This is deliberately simple
# (one shared login, browser's native basic-auth prompt) -- it's meant to keep
# the app off of casual/accidental access, not to withstand a targeted attack.
APP_USERNAME = os.environ.get("APP_USERNAME", "family")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

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
                    category TEXT NOT NULL,
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


@app.on_event("startup")
def on_startup():
    init_db()


class EntryIn(BaseModel):
    entry_date: date
    entry_time: Optional[time] = None
    category: str
    setting: Optional[str] = None
    duration_minutes: Optional[int] = None
    intensity: Optional[int] = None
    trigger: Optional[str] = None
    notes: Optional[str] = None
    logged_by: Optional[str] = None


class CategoryIn(BaseModel):
    name: str


@app.get("/api/health")
def health():
    return {"status": "ok", "db_configured": bool(DATABASE_URL)}


@app.get("/api/entries")
def list_entries():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM entries "
                "ORDER BY entry_date DESC, entry_time DESC NULLS LAST, id DESC"
            )
            rows = cur.fetchall()
    return rows


@app.post("/api/entries")
def create_entry(entry: EntryIn):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO entries
                    (entry_date, entry_time, category, setting, duration_minutes,
                     intensity, trigger, notes, logged_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    entry.entry_date,
                    entry.entry_time,
                    entry.category,
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
def delete_entry(entry_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
            deleted = cur.rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"deleted": entry_id}


@app.get("/api/categories")
def list_categories():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM categories ORDER BY name")
            rows = cur.fetchall()
    return [r[0] for r in rows]


@app.post("/api/categories")
def create_category(category: CategoryIn):
    name = category.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
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
