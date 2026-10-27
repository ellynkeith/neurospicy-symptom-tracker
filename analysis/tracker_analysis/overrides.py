"""Private, record-specific overrides.

The repo is public, so anything that names a specific incident, date or
medication lives in a JSON file outside git (default:
"Claude outputs/analysis/overrides.json"). This module only knows the
*shape* of that file; see overrides.example.json for a fake example.

The app reads the same JSON from the ANALYSIS_OVERRIDES environment variable
(see from_dict), so it stays out of the repo there too.

Keys (all optional):
  wetting_response    {incident_id: response}      applied before the generic "other" rule
  wetting_exclude     {incident_id: reason}        dropped from daytime-wetting analysis
  exclude_entries     {entry_id: reason}           dropped from behavior entries
  category_map        {old_category: new_category} extra mappings on top of the generic ones
  sleep_exclude       {date: reason}               sleep values for that night set to missing
  pending             [str, ...]                   open decisions, printed on every build
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Overrides:
    wetting_response: dict[str, str] = field(default_factory=dict)
    wetting_exclude: dict[str, str] = field(default_factory=dict)
    exclude_entries: dict[str, str] = field(default_factory=dict)
    category_map: dict[str, str] = field(default_factory=dict)
    sleep_exclude: dict[str, str] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    source: str = "(none)"

    @classmethod
    def load(cls, path: str | Path | None) -> "Overrides":
        if path is None or not Path(path).exists():
            return cls()
        return cls.from_dict(json.loads(Path(path).read_text()), source=str(path))

    @classmethod
    def from_dict(cls, d: dict, source: str = "(dict)") -> "Overrides":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k != "source"}
        unknown = set(d) - set(cls.__dataclass_fields__) - {"_comment"}
        if unknown:
            raise ValueError(f"Unknown override keys in {source}: {sorted(unknown)}")
        o = cls(**known)
        o.source = source
        # ids arrive as JSON keys (strings); normalise so lookups match the export's string ids
        for k in ("wetting_response", "wetting_exclude", "exclude_entries"):
            setattr(o, k, {str(i): v for i, v in getattr(o, k).items()})
        return o
