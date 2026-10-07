import os
from contextlib import contextmanager

import psycopg2
from fastapi import HTTPException

from models import DEFAULT_CATEGORIES, DEFAULT_SITUATIONS

DATABASE_URL = os.environ.get("DATABASE_URL")


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
                CREATE TABLE IF NOT EXISTS situations (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_logs (
                    entry_date DATE PRIMARY KEY,
                    bedtime TIME,
                    wake_time TIME,
                    night_awakenings INTEGER,
                    exercise_minutes INTEGER,
                    exercise_type TEXT
                )
                """
            )
            # Added after daily_logs already existed on some deployments --
            # bedtime (lights out / got in bed) and fell_asleep_time (sleep
            # actually started) are distinct and both worth tracking
            # separately (sleep-onset latency is its own signal). Plain
            # ADD COLUMN IF NOT EXISTS is enough here since it's a single
            # nullable column, no data to preserve/transform.
            cur.execute(
                "ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS fell_asleep_time TIME"
            )
            # Day-level outcome (added 2026-09-28). good_day is an explicit
            # "reviewed, nothing worth logging" marker so a quiet day is
            # distinguishable from a day nobody opened the app -- NULL means
            # not answered, never "bad day". day_rating (1-5) and day_notes
            # can be filled in on any day, good or not. All nullable/additive.
            cur.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS good_day BOOLEAN")
            cur.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS day_rating INTEGER")
            cur.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS day_notes TEXT")
            # Completeness view (added 2026-10-07): gaps_ok marks a day as
            # "nothing more to add" so gaps that can't be filled in (e.g.
            # last month's bedtime) stop being flagged as missing.
            cur.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS gaps_ok BOOLEAN")
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
                    situations TEXT[] NOT NULL DEFAULT '{}',
                    notes TEXT,
                    logged_by TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            # Brand new table -- unlike daily_logs there's nothing here to
            # migrate from, so CREATE TABLE IF NOT EXISTS alone covers both
            # a fresh install and an existing deployment.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS wetting_incidents (
                    id SERIAL PRIMARY KEY,
                    entry_date DATE NOT NULL,
                    incident_time TIME,
                    setting TEXT,
                    response TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            # Added after wetting_incidents already existed on some
            # deployments -- optional freeform space for anything the
            # time/where/response fields don't capture. Single nullable
            # column, nothing to preserve/transform.
            cur.execute(
                "ALTER TABLE wetting_incidents ADD COLUMN IF NOT EXISTS notes TEXT"
            )
            # Growable vocabulary, same shape as categories/situations --
            # free text, no default seed data (unlike categories/situations,
            # there's no sensible universal starter list for medications).
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS medications (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                )
                """
            )
            # Hide-without-deleting (added 2026-09-28): a med no longer in use
            # drops out of the picker but stays on its historical doses.
            cur.execute(
                "ALTER TABLE medications ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true"
            )
            # Brand new table, same shape as wetting_incidents -- plain
            # CREATE TABLE IF NOT EXISTS covers both a fresh install and an
            # existing deployment.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS medication_doses (
                    id SERIAL PRIMARY KEY,
                    entry_date DATE NOT NULL,
                    taken_time TIME,
                    medications TEXT[] NOT NULL DEFAULT '{}',
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            # A skipped dose is recorded explicitly (added 2026-10-07) so a
            # deliberate skip is distinguishable from a dose nobody logged.
            # Anything that analyses doses must exclude skipped rows.
            cur.execute(
                "ALTER TABLE medication_doses ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT false"
            )
            for cat in DEFAULT_CATEGORIES:
                cur.execute(
                    "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    (cat,),
                )
            for situation in DEFAULT_SITUATIONS:
                cur.execute(
                    "INSERT INTO situations (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    (situation,),
                )
        conn.commit()
    # One-off medication -> medications[] conversion (0e97815) also used to
    # run above; removed 2026-09-28 once it had run in production.
    # Three one-off migrations (singular category -> categories[],
    # retired-taxonomy cleanup, trigger -> situations) used to run here.
    # Removed 2026-09-09: all three target schema states this deployment
    # moved past long ago (confirmed via the live app's history: commits
    # baed264 and c9031d7), so they'd become permanent no-ops that still
    # paid for a fresh DB connection each on every single startup. See git
    # history if a from-scratch database somehow needs them again.
