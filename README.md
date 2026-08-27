# StoryGraph Automation

A Python automation tool that syncs reading and listening activity from **Goodreads** and **Audible** into **StoryGraph**.

---

## Features

### Goodreads -> StoryGraph
- Syncs **finished books** from Goodreads into StoryGraph
- Automatically sets:
  - Reading status = **Read**
  - Start date
  - Finish date
- Forces a **physical edition** so Goodreads reads don't land on StoryGraph as audiobooks
- Supports **multiple profiles** (separate Goodreads + StoryGraph accounts)
- Profile-scoped state prevents duplicate uploads
- Seed mode allows bootstrapping historical reads without touching StoryGraph

### Audible -> StoryGraph
- Syncs **in-progress audiobook progress**
- Detects:
  - New books
  - Progress changes
- Updates StoryGraph percentage progress
- Forces an **audiobook edition** and remembers it (per-book URL in sync state) for stable re-sync
- Handles StoryGraph search quirks (`&`, parentheticals, `:` subtitles) by retrying with simplified queries
- Handles duplicate StoryGraph catalog entries (picks the record on the reader's shelf)
- Verifies each write and only advances sync state on success — failed updates retry next run instead of being silently dropped
- Maintains per-profile sync state

### Automation-Ready
- Safe for **headless execution**
- Robust against partial failures (timeouts, missing data)
- Append-only logging with timestamps
- Designed to run **hourly or daily** via cron

---

## Profiles

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

## Docker Setup (Recommended)

Everything runs in Docker containers via `docker-compose.yml`.

### First-time setup

```bash
docker compose build
cp -r /path/to/audible-config/. audible-config/   # copy Audible CLI auth
cp /path/to/profiles/*.json profiles/              # copy profile credentials
```

### Scheduled runs

Add to crontab (`crontab -e`):
```cron
# Goodreads -> StoryGraph (Kim) — every hour on the hour
0 * * * * /path/to/storygraph-automation/docker/run-goodreads-kim.sh

# Audible -> StoryGraph (Justin) — 11:55 AM and 11:55 PM daily
55 11,23 * * * /path/to/storygraph-automation/docker/run-audible-justin.sh
```

### MFA recovery

If a run hangs on CAPTCHA/MFA, use the VNC-enabled variant:
```bash
docker compose --profile mfa run --rm --service-ports goodreads-kim-mfa
# Open http://localhost:6080/vnc.html to interact with the browser
```

---

## Local Usage (without Docker)

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

### Fix a single book's format

One-off helper to correct a book that was logged in the wrong format (e.g. an
older sync that landed as an audiobook). Switches the edition, preserving read
dates / progress:

```bash
python -m storygraph.fix_format --profile name --title "Book Title" --format physical
python -m storygraph.fix_format --profile name --title "Book Title" --format audiobook
```

---

## Logging

Logs are **append-only** and stored per profile.

Each run includes:
- Timestamped headers
- Mode (DRY RUN / APPLY)
- Books processed
- Skipped entries (with reasons)
- Runtime duration

| Log | Contents |
|-----|----------|
| `logs/goodreads/{profile}.log` | Goodreads run log; on a crash, `RUN FAILED` + full traceback |
| `logs/runner/{profile}.log` | Audible run log; on a crash, `RUN FAILED` + full traceback |
| `logs/cron/{service}.log` | Raw container stdout/stderr per cron run, plus exit code |

A crashed run writes `"status": "failed"` and the error message into
`status/status.json`, so a broken sync is visible there rather than looking like
a run that simply hasn't happened yet.

---

## Notes & Limitations

- Goodreads timelines are lazily loaded — the scraper accounts for this
- Missing or partial Goodreads data is safely skipped
- CAPTCHA or MFA challenges may require manual intervention
- This project is for **personal use only**

---

## License

This project is provided as-is for personal experimentation.
No affiliation with Goodreads, Amazon, or StoryGraph.
