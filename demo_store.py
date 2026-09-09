import itertools
import threading
from datetime import date, timedelta

from models import (
    DEFAULT_CATEGORIES,
    DEFAULT_SITUATIONS,
    DailyLogIn,
    EntryIn,
    WettingIncidentIn,
)


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
        self.situations = list(DEFAULT_SITUATIONS)
        self.entries = []
        self.daily_logs = {}
        self.wetting_incidents = []
        self._seed()

    def _next_id(self):
        return next(self._id_counter)

    def _seed(self):
        today = date.today()
        seed_rows = [
            dict(
                days_ago=0, entry_time="16:45", categories=["angry/irritable", "argumentative/defiant"], setting="home",
                duration_minutes=20, intensity=4, situations=["told no"],
                notes="Yelling and refusing to hand over the tablet after being told no to more screen time. Took about 20 min to de-escalate.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=0, entry_time="08:15", categories=["inattentive"], setting="school",
                duration_minutes=5, intensity=2, situations=["non-preferred task demand"],
                notes="Lost track partway through getting backpack ready (multi-step morning instructions), needed a re-prompt.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=1, entry_time="18:30", categories=["hyperactive/restless"], setting="home",
                duration_minutes=None, intensity=1, situations=[],
                notes="Couldn't stay seated through dinner, up and down repeatedly. Low-stakes, just noting the pattern.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=1, entry_time="07:50", categories=["impulsive"], setting="transitions",
                duration_minutes=10, intensity=3, situations=["waiting/turn-taking"],
                notes="Grabbed food off a sibling's plate without asking while waiting for breakfast, no warning first.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=2, entry_time="13:10", categories=["argumentative/defiant"], setting="public",
                duration_minutes=15, intensity=3, situations=["asked to transition off preferred activity"],
                notes="Asked to leave the playground; refused, argued about the rule itself rather than just not wanting to leave.",
                logged_by="Demo Parent",
            ),
            dict(
                days_ago=3, entry_time="15:00", categories=["hyperactive/restless", "impulsive"], setting="home",
                duration_minutes=30, intensity=1, situations=[],
                notes="High energy the whole afternoon, jumping between activities without finishing any.",
                logged_by="Demo Babysitter",
            ),
            dict(
                days_ago=4, entry_time="09:20", categories=["inattentive"], setting="school",
                duration_minutes=25, intensity=2, situations=["non-preferred task demand"],
                notes="Drifted off task repeatedly during independent seatwork, needed several redirects to finish the worksheet.",
                logged_by="Demo Teacher",
            ),
            dict(
                days_ago=5, entry_time="17:40", categories=["vindictive"], setting="home",
                duration_minutes=8, intensity=3, situations=["sibling conflict"],
                notes="Sibling was allowed to pick the show; deliberately broke a piece of the sibling's toy afterward, said it was on purpose.",
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
                    "situations": row["situations"],
                    "notes": row["notes"],
                    "logged_by": row["logged_by"],
                }
            )

        seed_daily = [
            dict(days_ago=0, bedtime="21:00", fell_asleep_time="21:35", wake_time="07:00",
                 night_awakenings=1, exercise_minutes=30, exercise_type="aerobic"),
            dict(days_ago=1, bedtime="21:30", fell_asleep_time="21:40", wake_time="06:45",
                 night_awakenings=0, exercise_minutes=20, exercise_type="cognitively-engaging"),
            dict(days_ago=3, bedtime="22:15", fell_asleep_time=None, wake_time="07:15",
                 night_awakenings=2, exercise_minutes=None, exercise_type=None),
        ]
        for row in seed_daily:
            entry_date = (today - timedelta(days=row["days_ago"])).isoformat()
            self.daily_logs[entry_date] = {
                "entry_date": entry_date,
                "bedtime": row["bedtime"],
                "fell_asleep_time": row["fell_asleep_time"],
                "wake_time": row["wake_time"],
                "night_awakenings": row["night_awakenings"],
                "exercise_minutes": row["exercise_minutes"],
                "exercise_type": row["exercise_type"],
            }

        seed_wetting = [
            dict(days_ago=0, incident_time="14:15", setting="school", response="noncompliant",
                 notes="Refused to change out of wet clothes for a few minutes."),
            dict(days_ago=2, incident_time="10:00", setting="home", response="compliant", notes=None),
        ]
        for row in seed_wetting:
            entry_date = (today - timedelta(days=row["days_ago"])).isoformat()
            self.wetting_incidents.append(
                {
                    "id": self._next_id(),
                    "entry_date": entry_date,
                    "incident_time": row["incident_time"],
                    "setting": row["setting"],
                    "response": row["response"],
                    "notes": row["notes"],
                }
            )

    def list_entries(self):
        with self._lock:
            return sorted(
                self.entries,
                key=lambda e: (e["entry_date"], e["entry_time"] or "", e["id"]),
                reverse=True,
            )

    def create_entry(self, entry: EntryIn):
        with self._lock:
            row = {
                "id": self._next_id(),
                "entry_date": entry.entry_date.isoformat(),
                "entry_time": entry.entry_time.isoformat() if entry.entry_time else None,
                "categories": entry.categories,
                "setting": entry.setting,
                "duration_minutes": entry.duration_minutes,
                "intensity": entry.intensity,
                "situations": entry.situations,
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

    def list_situations(self):
        with self._lock:
            return sorted(self.situations)

    def create_situation(self, name: str):
        with self._lock:
            if name not in self.situations:
                self.situations.append(name)

    def list_daily_logs(self):
        with self._lock:
            return sorted(self.daily_logs.values(), key=lambda r: r["entry_date"], reverse=True)

    def upsert_daily_log(self, log: DailyLogIn):
        with self._lock:
            row = {
                "entry_date": log.entry_date.isoformat(),
                "bedtime": log.bedtime.isoformat() if log.bedtime else None,
                "fell_asleep_time": log.fell_asleep_time.isoformat() if log.fell_asleep_time else None,
                "wake_time": log.wake_time.isoformat() if log.wake_time else None,
                "night_awakenings": log.night_awakenings,
                "exercise_minutes": log.exercise_minutes,
                "exercise_type": log.exercise_type,
            }
            self.daily_logs[row["entry_date"]] = row
            return row

    def list_wetting_incidents(self):
        with self._lock:
            return sorted(
                self.wetting_incidents,
                key=lambda w: (w["entry_date"], w["incident_time"] or "", w["id"]),
                reverse=True,
            )

    def create_wetting_incident(self, incident: WettingIncidentIn):
        with self._lock:
            row = {
                "id": self._next_id(),
                "entry_date": incident.entry_date.isoformat(),
                "incident_time": incident.incident_time.isoformat() if incident.incident_time else None,
                "setting": incident.setting,
                "response": incident.response,
                "notes": incident.notes,
            }
            self.wetting_incidents.append(row)
            return row

    def delete_wetting_incident(self, incident_id: int) -> bool:
        with self._lock:
            before = len(self.wetting_incidents)
            self.wetting_incidents = [w for w in self.wetting_incidents if w["id"] != incident_id]
            return len(self.wetting_incidents) != before


demo_store = DemoStore()
