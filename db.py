import os
from contextlib import contextmanager

import psycopg2
from fastapi import HTTPException

from models import DEFAULT_CATEGORIES, DEFAULT_SITUATIONS, RETIRED_DEFAULT_CATEGORIES

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
    migrate_single_category_column(conn=None)
    migrate_category_taxonomy(conn=None)
    migrate_trigger_to_situations(conn=None)


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


def migrate_trigger_to_situations(conn=None):
    """Replace the old freeform `trigger TEXT` column with the structured
    `situations TEXT[]` picker. Any existing freeform trigger text is folded
    into `notes` (prefixed "Trigger: ...") so nothing already logged is lost
    -- it just won't be one of the new structured, filterable tags. Safe to
    run on every startup: each step is a no-op once already applied.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'entries' AND column_name = 'situations'
                """
            )
            has_situations_column = cur.fetchone() is not None
            if not has_situations_column:
                cur.execute(
                    """
                    ALTER TABLE entries
                    ADD COLUMN situations TEXT[] NOT NULL DEFAULT '{}'
                    """
                )

            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'entries' AND column_name = 'trigger'
                """
            )
            has_trigger_column = cur.fetchone() is not None
            if has_trigger_column:
                cur.execute(
                    """
                    UPDATE entries
                    SET notes = CASE
                        WHEN notes IS NULL OR notes = '' THEN 'Trigger: ' || trigger
                        ELSE notes || E'\n\nTrigger: ' || trigger
                    END
                    WHERE trigger IS NOT NULL AND trigger <> ''
                    """
                )
                cur.execute("ALTER TABLE entries DROP COLUMN trigger")
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
