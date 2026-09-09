# Behavior & Symptom Log 🧠📋 #
A shared web app for logging behavioral patterns for a neurodivergent kid. Any caregiver — parents, a babysitter, a teacher — can log an entry from their own device, and the history stays in one place, filterable and exportable for appointments or school meetings.

## Try It ##
Live at [behavior-tracker-st8g.onrender.com](https://behavior-tracker-st8g.onrender.com/) — log in with `demo` / `demo` to click around with sample data. Demo logins are fully interactive (add, filter, delete) but run on an isolated in-memory dataset, so nothing you do there ever touches the real log. First load can take 30–60 seconds if the site's been idle (free hosting sleeps when nobody's using it) — that's normal, not broken.

## Screenshots ##
<img width="768" height="726" alt="image" src="https://github.com/user-attachments/assets/22c22feb-f220-4694-9822-f1e62dae1e0c" />
<img width="803" height="590" alt="image" src="https://github.com/user-attachments/assets/abaeac7f-a73d-465e-9910-2a0221ee9cf8" />

## What It Tracks ##
- [x] Shared Logging: any household device can add entries, no install or account creation required
- [x] Custom Categories: seeded with an evidence-based taxonomy matched to this kid's actual evaluated profile — DSM-5 ODD's three clusters (angry/irritable, argumentative/defiant, vindictive) plus the three ADHD presentations (impulsive, inattentive, hyperactive/restless) — add your own on the fly
- [x] Multi-Category Tagging: tag one entry with more than one category at once (e.g. angry/irritable + argumentative/defiant)
- [x] Situation/Demand Tagging: optionally tag what was going on right before (told no, a non-preferred task demand, sibling conflict, an unexpected change in plans, etc.) from a growable structured list, so situations can be clustered and compared instead of living in unstructured freeform text
- [x] Rich Entry Detail: date, time, setting, duration, 1–5 intensity scale, freeform notes, and who logged it
- [x] Daily Context: separately track sleep (bedtime, wake time, night awakenings) and exercise (duration + cognitively-engaging vs. aerobic vs. other) once per day, independent of how many behavior entries that day has — shows up alongside that day's entries when logged, including on days with no incidents at all
- [x] Day-Grouped History: entries organized chronologically, newest first
- [x] Category Filtering: narrow the log down to one category at a time
- [x] CSV Export: pull the full log (or a filtered slice) for appointments or school meetings
- [x] Shared Login: household-wide password gate so the log isn't wide open to the internet
- [x] Demo Mode: a separate login serves sample data so anyone can see how it works without seeing (or risking) the real log
- [ ] Data Insights: surface patterns over time — frequency by category, trends by setting or time of day, common situations/demands, correlations with sleep and exercise
- [ ] Edit Entries: currently delete-and-relog
- [ ] Automated Backups: beyond the manual CSV export
- [ ] Per-Person Accounts: currently one shared household login

## Architecture ##
Caregiver's Device → FastAPI Backend → Postgres (Neon) → Shared History Across All Devices

## Tech Stack ##
### Backend
- FastAPI
- Uvicorn

### Database
- PostgreSQL, hosted on Neon (serverless, free tier)
- psycopg2

### Hosting
- Render (free web service)
- Neon (free Postgres)

**Frontend**
* HTML/CSS (warm, non-clinical styling — paper background, serif headings, no cards or shadows)
* Vanilla JavaScript, no build step
