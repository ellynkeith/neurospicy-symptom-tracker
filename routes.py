import csv
import io
import re
import zipfile
from typing import Optional

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from auth import is_demo, is_read_only
from db import DATABASE_URL, get_conn
from demo_store import demo_store
from models import (
    CategoryIn,
    DailyLogIn,
    EntryIn,
    GapsOkIn,
    MedicationDoseIn,
    MedicationIn,
    MedicationVisibilityIn,
    SituationIn,
    WettingIncidentIn,
)

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "db_configured": bool(DATABASE_URL)}


@router.get("/api/whoami")
def whoami(request: Request):
    return {"demo": is_demo(request), "read_only": is_read_only(request)}


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
                     exercise_minutes, exercise_type, good_day, day_rating, day_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entry_date) DO UPDATE SET
                    good_day = EXCLUDED.good_day,
                    day_rating = EXCLUDED.day_rating,
                    day_notes = EXCLUDED.day_notes,
                    bedtime = EXCLUDED.bedtime,
                    fell_asleep_time = EXCLUDED.fell_asleep_time,
                    wake_time = EXCLUDED.wake_time,
                    night_awakenings = EXCLUDED.night_awakenings,
                    -- Exercise is no longer edited via the UI (removed
                    -- 2026-09-25) and the daily form no longer sends it, so
                    -- preserve whatever's already stored instead of nulling
                    -- it out on every sleep-only save.
                    exercise_minutes = COALESCE(EXCLUDED.exercise_minutes, daily_logs.exercise_minutes),
                    exercise_type = COALESCE(EXCLUDED.exercise_type, daily_logs.exercise_type)
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
                    log.good_day,
                    log.day_rating,
                    log.day_notes,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


# Separate from the /api/daily upsert on purpose: that one replaces the whole
# row, and marking a day "nothing more to add" must never touch its sleep or
# rating fields.
@router.post("/api/daily/gaps-ok")
def set_gaps_ok(body: GapsOkIn, request: Request):
    value = True if body.ok else None
    if is_demo(request):
        demo_store.set_gaps_ok([d.isoformat() for d in body.dates], value)
        return {"dates": [d.isoformat() for d in body.dates], "gaps_ok": value}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for d in body.dates:
                cur.execute(
                    """
                    INSERT INTO daily_logs (entry_date, gaps_ok) VALUES (%s, %s)
                    ON CONFLICT (entry_date) DO UPDATE SET gaps_ok = EXCLUDED.gaps_ok
                    """,
                    (d, value),
                )
        conn.commit()
    return {"dates": [d.isoformat() for d in body.dates], "gaps_ok": value}


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


@router.put("/api/wetting/{incident_id}")
def update_wetting_incident(incident_id: int, incident: WettingIncidentIn, request: Request):
    if is_demo(request):
        updated = demo_store.update_wetting_incident(incident_id, incident)
        if updated is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return updated
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE wetting_incidents
                SET entry_date = %s, incident_time = %s, setting = %s, response = %s, notes = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    incident.entry_date,
                    incident.incident_time,
                    incident.setting,
                    incident.response,
                    incident.notes,
                    incident_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
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


@router.get("/api/medications")
def list_medications(request: Request):
    if is_demo(request):
        return demo_store.list_medications()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, active FROM medications ORDER BY name")
            rows = cur.fetchall()
    return [{"name": r[0], "active": r[1]} for r in rows]


@router.post("/api/medications")
def create_medication(medication: MedicationIn, request: Request):
    name = medication.name.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Medication name cannot be empty")
    if is_demo(request):
        demo_store.create_medication(name)
        return {"name": name}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                # Re-adding a hidden med via "+ new" un-hides it.
                "INSERT INTO medications (name) VALUES (%s) "
                "ON CONFLICT (name) DO UPDATE SET active = true",
                (name,),
            )
        conn.commit()
    return {"name": name}


# Body rather than a path param: med names can contain "/" (e.g.
# "l-theanine/magnesium"), which would break a /api/medications/{name} route.
@router.post("/api/medications/visibility")
def set_medication_visibility(body: MedicationVisibilityIn, request: Request):
    name = body.name.strip().lower()
    if is_demo(request):
        if not demo_store.set_medication_active(name, body.active):
            raise HTTPException(status_code=404, detail="Medication not found")
        return {"name": name, "active": body.active}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE medications SET active = %s WHERE name = %s",
                (body.active, name),
            )
            updated = cur.rowcount
        conn.commit()
    if not updated:
        raise HTTPException(status_code=404, detail="Medication not found")
    return {"name": name, "active": body.active}


@router.get("/api/medication-doses")
def list_medication_doses(request: Request):
    if is_demo(request):
        return demo_store.list_medication_doses()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM medication_doses "
                "ORDER BY entry_date DESC, taken_time DESC NULLS LAST, id DESC"
            )
            rows = cur.fetchall()
    return rows


@router.post("/api/medication-doses")
def create_medication_dose(dose: MedicationDoseIn, request: Request):
    if is_demo(request):
        return demo_store.create_medication_dose(dose)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO medication_doses
                    (entry_date, taken_time, medications, notes, skipped)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    dose.entry_date,
                    dose.taken_time,
                    dose.medications,
                    dose.notes,
                    dose.skipped,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.put("/api/medication-doses/{dose_id}")
def update_medication_dose(dose_id: int, dose: MedicationDoseIn, request: Request):
    if is_demo(request):
        updated = demo_store.update_medication_dose(dose_id, dose)
        if updated is None:
            raise HTTPException(status_code=404, detail="Dose not found")
        return updated
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE medication_doses
                SET entry_date = %s, taken_time = %s, medications = %s, notes = %s, skipped = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    dose.entry_date,
                    dose.taken_time,
                    dose.medications,
                    dose.notes,
                    dose.skipped,
                    dose_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="Dose not found")
    return row


@router.delete("/api/medication-doses/{dose_id}")
def delete_medication_dose(dose_id: int, request: Request):
    if is_demo(request):
        if not demo_store.delete_medication_dose(dose_id):
            raise HTTPException(status_code=404, detail="Dose not found")
        return {"deleted": dose_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM medication_doses WHERE id = %s", (dose_id,))
            deleted = cur.rowcount
        conn.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Dose not found")
    return {"deleted": dose_id}


# ---------------------------------------------------------------------------
# Full export: one tidy CSV per table, zipped. Explicit column lists (rather
# than SELECT *) keep the column order stable across schema changes. Array
# columns are joined with "; ", same as the behavior-only CSV in the UI.
# ---------------------------------------------------------------------------
EXPORT_TABLES = {
    "entries.csv": (
        "entries",
        ["id", "entry_date", "entry_time", "categories", "setting", "duration_minutes",
         "intensity", "situations", "notes", "logged_by", "created_at"],
        "entry_date, entry_time NULLS LAST, id",
    ),
    "daily.csv": (
        "daily_logs",
        ["entry_date", "good_day", "day_rating", "day_notes", "wake_time", "bedtime",
         "fell_asleep_time", "night_awakenings", "exercise_minutes", "exercise_type", "gaps_ok"],
        "entry_date",
    ),
    "wetting_incidents.csv": (
        "wetting_incidents",
        ["id", "entry_date", "incident_time", "setting", "response", "notes", "created_at"],
        "entry_date, incident_time NULLS LAST, id",
    ),
    "medication_doses.csv": (
        "medication_doses",
        ["id", "entry_date", "taken_time", "medications", "skipped", "notes", "created_at"],
        "entry_date, taken_time NULLS LAST, id",
    ),
}


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _to_csv(columns, rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_value(row.get(c)) for c in columns])
    # utf-8-sig (BOM) so Excel reads non-ASCII in notes correctly; pandas
    # strips the BOM automatically.
    return buf.getvalue().encode("utf-8-sig")


def _demo_export_rows(filename):
    key = lambda r, t: (r["entry_date"], r.get(t) or "99", r.get("id", 0))
    if filename == "entries.csv":
        return sorted(demo_store.list_entries(), key=lambda r: key(r, "entry_time"))
    if filename == "daily.csv":
        return sorted(demo_store.list_daily_logs(), key=lambda r: r["entry_date"])
    if filename == "wetting_incidents.csv":
        return sorted(demo_store.list_wetting_incidents(), key=lambda r: key(r, "incident_time"))
    return sorted(demo_store.list_medication_doses(), key=lambda r: key(r, "taken_time"))


@router.get("/api/export")
def export_all(request: Request, date: Optional[str] = None):
    # The browser passes its local date for the filename -- the server runs
    # in UTC, which would stamp evening exports with tomorrow's date.
    if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    zip_name = f"behavior-tracker-export-{date}.zip" if date else "behavior-tracker-export.zip"
    tables = {}
    if is_demo(request):
        for filename, (_, columns, _) in EXPORT_TABLES.items():
            tables[filename] = (columns, _demo_export_rows(filename))
    else:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for filename, (table, columns, order_by) in EXPORT_TABLES.items():
                    # Table/column names come from the constant above, never
                    # from the request, so string-building here is safe.
                    cur.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order_by}")
                    tables[filename] = (columns, cur.fetchall())

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, (columns, rows) in tables.items():
            zf.writestr(filename, _to_csv(columns, rows))
    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
