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
- StoryGraph search has quirks with `&`, `,`/parentheticals, and `:` subtitles (e.g. `Allegiance: Star Wars Legends` returns nothing) — `search_book_with_fallbacks` (`runner_api.py`) retries with progressively stripped queries before giving up. Both `update_books_read` (Goodreads) and `update_books_progress` (Audible) go through it, so the quirk handling lives in one place
- Duplicate StoryGraph entries (same title+author) are disambiguated in `find_matching_book` (`navigate_flow.py`): drop "user-added"/unreviewed entries, then prefer the one with the most editions. For *progress* updates, `find_progress_match` adds a final fallback: if both duplicates still look identical, pick the one that already shows reading progress (the record actually on the reader's shelf)
- `set_read_dates` (`read_dates_flow.py`) only fills *missing* read dates, so it won't clobber dates a reader set by hand and won't crash on an already-read book
- Each book in `update_books_read` and `update_books_progress` is wrapped in try/except, so one bad book is logged and skipped (retried next run) rather than aborting the whole sync
- `update_books_progress` returns a mapping of `title -> settled edition URL` for the books it *verified* on StoryGraph; `runner.py` only advances sync state for those (failed/skipped books keep their prior value so they retry next run) and logs per-book `OK (synced)` / `FAILED (…will retry)` to `logs/runner/{profile}.log`. Never advance sync state on an unverified write — that silently masks failures and the book is never retried
- **Format is per-edition, not per-book.** On StoryGraph the format (paperback/hardcover/digital-ebook/audio) comes from the *edition* on the shelf, which StoryGraph picks inconsistently. We force it by source: Goodreads (Kim) → physical, Audible (Justin) → audiobook. `ensure_book_format` (`flows/edition_flow.py`) opens the book's `/editions` page and, if the current edition is the wrong kind, submits the `/switch-editions` form for a matching English edition — which *moves the reading history* (status/dates/progress) to it. It is **best-effort and never raises**: the read/progress write happens first and is what gets recorded; a format miss is only logged. The Audible path persists the settled audiobook edition URL in `sync_{profile}.json` (`book_url`) and navigates straight to it on later runs, so a switch to a less-popular audio edition can't break progress re-sync. One-off backfill: `python -m storygraph.fix_format --profile <p> --title "<t>" --format physical|audiobook`

## Testing changes

### Via Docker (production path)

Source is baked into the image at build time — **after editing any `.py` you must `docker compose build`** or the container (and cron) keep running the old code. A stale image silently running pre-fix code has already caused a production bug.

```
docker compose build                                                       # required after code edits
docker compose run --rm goodreads-kim python -m goodreads --profile kim    # dry-run
docker compose run --rm audible-justin                                     # diffs only if no changes
```

### Local (without Docker)
```
python -m goodreads --profile kim          # dry-run (safe)
python runner.py --profile justin          # diffs only if no changes
```
