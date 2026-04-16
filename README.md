# StoryGraph Automation

A Python automation tool that syncs reading and listening activity from **Goodreads** and **Audible** into **StoryGraph**.

---

## ✨ Features

### 📚 Goodreads -> StoryGraph
- Syncs **finished books** from Goodreads into StoryGraph
- Automatically sets:
  - Reading status = **Read**
  - Start date
  - Finish date
- Supports **multiple profiles** (separate Goodreads + StoryGraph accounts)
- Profile-scoped state prevents duplicate uploads
- Seed mode allows bootstrapping historical reads without touching StoryGraph

### 🎧 Audible -> StoryGraph
- Syncs **in-progress audiobook progress**
- Detects:
  - New books
  - Progress changes
- Updates StoryGraph percentage progress
- Maintains per-profile sync state

### 🕒 Automation-Ready
- Safe for **headless execution**
- Robust against partial failures (timeouts, missing data)
- Append-only logging with timestamps
- Designed to run **hourly or daily** via Task Scheduler

---

## 👤 Profiles

Profiles live in the `profiles/` directory and are **not committed**.

Each profile defines credentials for all supported services:

```json
{
  "goodreads_email": "user@example.com",
  "goodreads_password": "password",
  "storygraph_email": "user@example.com",
  "storygraph_password": "password"
}
```

Profiles allow:
- Multiple Goodreads accounts
- Multiple StoryGraph accounts
- Clean separation of state and browser sessions

---

## 🐳 Docker Setup (Recommended)

Everything runs in Docker containers via `docker-compose.yml`.

### First-time setup

```bash
docker compose build
cp -r "$LOCALAPPDATA/Audible/." audible-config/   # copy Audible CLI auth
docker compose up -d dashboard                      # start status API on port 1200
```

### Scheduled runs

Triggered by Windows Task Scheduler (or cron):
```bash
docker compose run --rm goodreads-kim      # Goodreads -> StoryGraph (Kim)
docker compose run --rm audible-justin     # Audible -> StoryGraph (Justin)
```

### Status dashboard

```bash
curl http://localhost:1200/status    # JSON: last run, next run, per-profile state
curl http://localhost:1200/healthz   # health check
```

### MFA recovery

If a run hangs on CAPTCHA/MFA, use the VNC-enabled variant:
```bash
docker compose --profile mfa run --rm --service-ports goodreads-kim-mfa
# Open http://localhost:6080/vnc.html to interact with the browser
```

---

## 🚀 Local Usage (without Docker)

### Goodreads -> StoryGraph (Dry Run)

```bash
python -m goodreads --profile name
```

### Goodreads -> StoryGraph (Apply)

```bash
python -m goodreads --profile name --apply
```

### Seed Goodreads History (No StoryGraph Writes)

Marks all books finished before a date as already processed:

```bash
python -m goodreads --profile name --seed-before 2026-02-01
```

This is useful when:
- Migrating an existing Goodreads library
- Avoiding mass uploads to StoryGraph

---

### Audible -> StoryGraph

```bash
python runner.py --profile name
```

- Detects new or changed progress
- Updates StoryGraph only when needed
- Saves per-profile sync state

---

## 📝 Logging

Logs are **append-only** and stored per profile

Each run includes:
- Timestamped headers
- Mode (DRY RUN / APPLY)
- Books processed
- Skipped entries (with reasons)
- Runtime duration

Designed for long-running scheduled automation.

---

## ⚠️ Notes & Limitations

- Goodreads timelines are lazily loaded — the scraper accounts for this
- Missing or partial Goodreads data is safely skipped
- CAPTCHA or MFA challenges may require manual intervention
- This project is for **personal use only**

---

## 🔧 Future Improvements

- Retry logic for transient failures
- Email / Discord notifications
- ~~Configurable schedules~~ ✅ via `dashboard/schedules.yml`
- CSV / JSON export modes
- ~~Unified dashboard view~~ ✅ via `GET /status` on port 1200

---

## 📜 License

This project is provided as-is for personal experimentation.
No affiliation with Goodreads, Amazon, or StoryGraph.
