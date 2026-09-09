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
    # Three one-off migrations (singular category -> categories[],
    # retired-taxonomy cleanup, trigger -> situations) used to run here.
    # Removed 2026-09-09: all three target schema states this deployment
    # moved past long ago (confirmed via the live app's history: commits
    # baed264 and c9031d7), so they'd become permanent no-ops that still
    # paid for a fresh DB connection each on every single startup. See git
    # history if a from-scratch database somehow needs them again.
