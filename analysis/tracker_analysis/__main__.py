"""Build analysis tables from an export.

    python -m tracker_analysis "../Claude outputs/data/export-2026-10-19_1803.zip"

Defaults: overrides from "../Claude outputs/analysis/overrides.json", output to
"../Claude outputs/analysis/build/". Both are inside the gitignored folder --
built tables contain real data and must never be committed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import Overrides, Params, build, load_export

PRIVATE = Path(__file__).resolve().parents[2] / "Claude outputs"


def latest_export() -> Path | None:
    exports = sorted((PRIVATE / "data").glob("export-*.zip"))
    return exports[-1] if exports else None


def write(result, out: Path, export: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in result.tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
    lines = [f"# Transformation log", "",
             f"Built {datetime.now():%Y-%m-%d %H:%M} from `{export.name}`; overrides: `{Path(result.overrides_source).name}`.",
             f"Params: {result.params}", "",
             "| step | what | rows | detail |", "|---|---|---|---|"]
    for r in result.log:
        lines.append(f"| {r.id} | **{r.title}** — {r.why} | {r.rows} | {r.detail} |")
    if result.pending:
        lines += ["", "## Pending decisions", ""] + [f"- {p}" for p in result.pending]
    (out / "transformation_log.md").write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tracker_analysis")
    ap.add_argument("export", nargs="?", help="export zip or extracted folder (default: newest in Claude outputs/data)")
    ap.add_argument("--overrides", default=str(PRIVATE / "analysis" / "overrides.json"))
    ap.add_argument("--out", default=str(PRIVATE / "analysis" / "build"))
    ap.add_argument("--through", help="last complete day (YYYY-MM-DD); default: day before the export")
    a = ap.parse_args(argv)

    export = Path(a.export) if a.export else latest_export()
    if export is None:
        print("No export found.", file=sys.stderr)
        return 1
    ov = Overrides.load(a.overrides)
    if ov.source == "(none)":
        print(f"warning: no overrides file at {a.overrides}; generic rules only", file=sys.stderr)
    res = build(load_export(export), ov, Params(through=a.through), export_name=export.name)
    write(res, Path(a.out), export)
    print(f"{export.name} -> {a.out}")
    for r in res.log:
        print(f"  {r.id:5} {r.rows:4}  {r.title}")
    for p in res.pending:
        print(f"  PENDING: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
