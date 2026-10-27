"""Read a tracker export zip (GET /api/export) into raw DataFrames.

Everything is read as strings with blanks kept as "" so that no cleaning
happens implicitly here -- every change to the data is a named step in
transform.py and shows up in the transformation log.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

TABLES = ["entries", "daily", "wetting_incidents", "context_events", "medication_doses"]


def load_export(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    raw: dict[str, pd.DataFrame] = {}
    if path.is_dir():
        for t in TABLES:
            p = path / f"{t}.csv"
            raw[t] = _read(p.read_bytes()) if p.exists() else pd.DataFrame()
    else:
        with zipfile.ZipFile(path) as z:
            names = {Path(n).stem: n for n in z.namelist()}
            for t in TABLES:
                raw[t] = _read(z.read(names[t])) if t in names else pd.DataFrame()
    return raw


def load_tables(files: dict[str, bytes]) -> dict[str, pd.DataFrame]:
    """Same as load_export, from CSV bytes already in memory ({"entries": b"...", ...}).

    The app uses this to run the analysis on the exact CSVs /api/export would
    produce, so the server and the notebook read identical input.
    """
    return {t: _read(files[t]) if t in files else pd.DataFrame() for t in TABLES}


def _read(data: bytes) -> pd.DataFrame:
    # utf-8-sig strips the BOM the export writes (so the first column isn't "﻿id")
    return pd.read_csv(io.StringIO(data.decode("utf-8-sig")), dtype=str, keep_default_na=False)
