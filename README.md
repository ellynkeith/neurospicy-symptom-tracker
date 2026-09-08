# Behavior & Symptom Log 🧠📋 #
A shared web app for logging behavioral and sensory patterns for a neurodivergent kid. Any caregiver — parents, a babysitter, a teacher — can log an entry from their own device, and the history stays in one place, filterable and exportable for appointments or school meetings.

<img width="806" height="728" alt="image" src="https://github.com/user-attachments/assets/5b3f596f-b802-4808-bd55-01880df48232" />
 
## What It Tracks ##
- [x] Shared Logging: any household device can add entries, no install or account creation required
- [x] Custom Categories: seeded with meltdown, shutdown, sensory seeking, sensory avoidance, stimming, anxiety, rigidity, and aggression — add your own on the fly
- [x] Rich Entry Detail: date, time, setting, duration, 1–5 intensity scale, possible trigger, freeform notes, and who logged it
- [x] Day-Grouped History: entries organized chronologically, newest first
- [x] Category Filtering: narrow the log down to one category at a time
- [x] CSV Export: pull the full log (or a filtered slice) for appointments or school meetings
- [x] Shared Login: household-wide password gate so the log isn't wide open to the internet
- [ ] Edit Entries: currently delete-and-relog
- [ ] Automated Backups: beyond the manual CSV export
- [ ] Per-Person Accounts: currently one shared household login

<img width="883" height="393" alt="image" src="https://github.com/user-attachments/assets/ee6a4bfd-7936-444f-8633-af75a3ea5f7d" />

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
