import psycopg2.extras
from fastapi import APIRouter, HTTPException, Request

from auth import is_demo
from db import DATABASE_URL, get_conn
from demo_store import demo_store
from models import CategoryIn, DailyLogIn, EntryIn, SituationIn, WettingIncidentIn

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "db_configured": bool(DATABASE_URL)}


@router.get("/api/whoami")
def whoami(request: Request):
    return {"demo": is_demo(request)}


@router.get("/api/entries")
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


@router.post("/api/entries")
def create_entry(entry: EntryIn, request: Request):
    if is_demo(request):
        return demo_store.create_entry(entry)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO entries
                    (entry_date, entry_time, categories, setting, duration_minutes,
                     intensity, situations, notes, logged_by)
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
                    entry.situations,
                    entry.notes,
                    entry.logged_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, entry: EntryIn, request: Request):
    if is_demo(request):
        updated = demo_store.update_entry(entry_id, entry)
        if updated is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return updated
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE entries
                SET entry_date = %s, entry_time = %s, categories = %s, setting = %s,
                    duration_minutes = %s, intensity = %s, situations = %s, notes = %s,
                    logged_by = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    entry.entry_date,
                    entry.entry_time,
                    entry.categories,
                    entry.setting,
                    entry.duration_minutes,
                    entry.intensity,
                    entry.situations,
                    entry.notes,
                    entry.logged_by,
                    entry_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return row


@router.delete("/api/entries/{entry_id}")
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


@router.get("/api/categories")
def list_categories(request: Request):
    if is_demo(request):
        return demo_store.list_categories()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM categories ORDER BY name")
            rows = cur.fetchall()
    return [r[0] for r in rows]


@router.post("/api/categories")
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


@router.get("/api/situations")
def list_situations(request: Request):
    if is_demo(request):
        return demo_store.list_situations()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM situations ORDER BY name")
            rows = cur.fetchall()
    return [r[0] for r in rows]


@router.post("/api/situations")
def create_situation(situation: SituationIn, request: Request):
    name = situation.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Situation name cannot be empty")
    if is_demo(request):
        demo_store.create_situation(name)
        return {"name": name}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO situations (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                (name,),
            )
        conn.commit()
    return {"name": name}


@router.get("/api/daily")
def list_daily_logs(request: Request):
    if is_demo(request):
        return demo_store.list_daily_logs()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM daily_logs ORDER BY entry_date DESC")
            rows = cur.fetchall()
    return rows


@router.post("/api/daily")
def upsert_daily_log(log: DailyLogIn, request: Request):
    if is_demo(request):
        return demo_store.upsert_daily_log(log)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO daily_logs
                    (entry_date, bedtime, fell_asleep_time, wake_time, night_awakenings,
                     exercise_minutes, exercise_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entry_date) DO UPDATE SET
                    bedtime = EXCLUDED.bedtime,
                    fell_asleep_time = EXCLUDED.fell_asleep_time,
                    wake_time = EXCLUDED.wake_time,
                    night_awakenings = EXCLUDED.night_awakenings,
                    exercise_minutes = EXCLUDED.exercise_minutes,
                    exercise_type = EXCLUDED.exercise_type
                RETURNING *
                """,
                (
                    log.entry_date,
                    log.bedtime,
                    log.fell_asleep_time,
                    log.wake_time,
                    log.night_awakenings,
                    log.exercise_minutes,
                    log.exercise_type,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.get("/api/wetting")
def list_wetting_incidents(request: Request):
    if is_demo(request):
        return demo_store.list_wetting_incidents()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM wetting_incidents "
                "ORDER BY entry_date DESC, incident_time DESC NULLS LAST, id DESC"
            )
            rows = cur.fetchall()
    return rows


@router.post("/api/wetting")
def create_wetting_incident(incident: WettingIncidentIn, request: Request):
    if is_demo(request):
        return demo_store.create_wetting_incident(incident)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO wetting_incidents
                    (entry_date, incident_time, setting, response, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    incident.entry_date,
                    incident.incident_time,
                    incident.setting,
                    incident.response,
                    incident.notes,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.delete("/api/wetting/{incident_id}")
def delete_wetting_incident(incident_id: int, request: Request):
    if is_demo(request):
        if not demo_store.delete_wetting_incident(incident_id):
            raise HTTPException(status_code=404, detail="Incident not found")
        return {"deleted": incident_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wetting_incidents WHERE id = %s", (incident_id,))
            deleted = cur.rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"deleted": incident_id}
