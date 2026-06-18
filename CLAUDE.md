# StoryGraphAutomation

Automates syncing reading activity into StoryGraph via Playwright browser automation.

## Architecture — Docker

Everything runs in Docker containers. One image, two services via `docker-compose.yml`:

| Service | Purpose | Lifecycle |
|---------|---------|-----------|
| `goodreads-kim` | Goodreads -> StoryGraph sync (Kim) | One-shot, fired by cron |
| `audible-justin` | Audible -> StoryGraph sync (Justin) | One-shot, fired by cron |

Xvfb provides a virtual display inside the container, so the existing `headless=False` code works unchanged.

### Cron schedule

```
# Kim: every hour on the hour
0 * * * * /home/talon/dev/storygraph-automation/docker/run-goodreads-kim.sh

# Justin: 11:55 AM and 11:55 PM daily
55 11,23 * * * /home/talon/dev/storygraph-automation/docker/run-audible-justin.sh
```

Edit with `crontab -e`.

### MFA recovery

If a run hangs on CAPTCHA or MFA, use the VNC-enabled variant:
```bash
docker compose --profile mfa run --rm --service-ports goodreads-kim-mfa
```
Then open `http://localhost:6080/vnc.html` to see the browser and complete the challenge manually.

### First-time setup

1. Build the image: `docker compose build`
2. Copy Audible CLI auth into the project:
   ```bash
   cp -r /path/to/audible-config/. audible-config/
   ```
3. Copy profile credentials:
   ```bash
   cp /path/to/profiles/*.json profiles/
   ```
4. Test a dry run: `docker compose run --rm goodreads-kim python -m goodreads --profile kim`

## Key conventions

- Credentials live in `profiles/{name}.json` (not committed). Never hardcode credentials.
- Audible CLI auth: `audible-config/` (bind-mounted, not committed). `AUDIBLE_CONFIG_DIR` env var points to it.
- Browser session state: `goodreads/state/` and `storygraph/state/`
- Sync state (processed book IDs): `goodreads/state/state_{profile}.json` and `storygraph/state/sync_{profile}.json`
- Logs: `logs/goodreads/{profile}.log` and `logs/runner/{profile}.log` (append-only, read from tail)
- Run status: `status/status.json` — written by both runners after each run (last run time, duration, sync counts, next scheduled run). `status.py` owns this.
- `storygraph/runner_api.py` exposes `storygraph_session()` context manager for browser lifecycle
- StoryGraph search has quirks with `&`, `,`/parentheticals, and `:` subtitles — `update_books_read` in `runner_api.py` retries with progressively stripped queries before giving up
- Duplicate StoryGraph entries (same title+author) are disambiguated in `find_matching_book` (`navigate_flow.py`): drop "user-added"/unreviewed entries, then prefer the one with the most editions
- `set_read_dates` (`read_dates_flow.py`) only fills *missing* read dates, so it won't clobber dates a reader set by hand and won't crash on an already-read book
- Each book in `update_books_read` is wrapped in try/except, so one bad book is logged and skipped (retried next run) rather than aborting the whole sync

## Testing changes

### Via Docker (production path)
```
docker compose run --rm goodreads-kim python -m goodreads --profile kim    # dry-run
docker compose run --rm audible-justin                                     # diffs only if no changes
```

### Local (without Docker)
```
python -m goodreads --profile kim          # dry-run (safe)
python runner.py --profile justin          # diffs only if no changes
```
