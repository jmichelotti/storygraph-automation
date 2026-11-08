# StoryGraphAutomation

Automates syncing reading activity into StoryGraph via Playwright browser automation.

## Architecture — Docker

Everything runs in Docker containers. One image, two services via `docker-compose.yml`:

| Service | Purpose | Lifecycle |
|---------|---------|-----------|
| `goodreads-kim` | Goodreads -> StoryGraph sync (Kim), her read export for reading-cards, then once a day her To-Read export for book-events | One-shot, fired by cron |
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
- Goodreads throttles bursts of runs: it answers with an aborted navigation (`net::ERR_ABORTED`) or an empty HTTP 202 body. `_goto_with_retry` (`goodreads/auth.py`) retries *any* navigation error — not just timeouts — with 10s/20s backoff. Don't fire manual runs back-to-back with the hourly cron; wait for the throttle to clear
- Audible CLI auth: `audible-config/` (bind-mounted, not committed). `AUDIBLE_CONFIG_DIR` env var points to it.
- Browser session state: `goodreads/state/` and `storygraph/state/`
- Sync state (processed book IDs): `goodreads/state/state_{profile}.json` and `storygraph/state/sync_{profile}.json`
- Logs: `logs/goodreads/{profile}.log` and `logs/runner/{profile}.log` (append-only, read from tail). Cron wrappers additionally tee the container's raw stdout/stderr to `logs/cron/{service}.log` with the exit code — without that, cron discards a crash entirely
- Run status: `status/status.json` — written by both runners after each run (last run time, duration, sync counts, next scheduled run). `status.py` owns this. `_next_run` steps with `timedelta`: until 2026-10-19 it built hour 24 at 23:xx UTC, and the 16:00 PDT Kim run crashed writing its status every day (103 times in `logs/cron/`), after its sync work had already finished
- **To-Read export for book-events** (`storygraph/to_read_export.py`, added 2026-10-19; ruled in book-events' round table `round-table/2026-10-19-book-fairs-and-to-read/`). book-events searches for authors Kim newly adds to her StoryGraph To-Read Pile. StoryGraph has no API, and this repo is the only one with her session, so the export lives here and book-events reads only the file it writes. After a successful `--apply` sync, `goodreads/runner.py` calls `export_to_read`. That export is due at most once per 20 hours, and 3 hours after a failed attempt. It finds her handle from the nav, skipping `/profile/edit`, then scrolls `/to-read/<handle>` to the end. It publishes `exports/<profile>-to-read.json` (`{schema: storygraph-to-read/1, handle, scraped_at, displayed_count, count, complete, books: [{id, title, authors}]}`) **only** if both checks pass: the "More..." link `#next_link` has become an empty span, and the unique book ids equal the page's printed count ("803 books" on 2026-10-19). Anything else keeps the last good file. The file is 0600, chowned to the owner of `exports/` (the container is root, book-events reads it as talon), and written to `.new`, then renamed. It holds no credentials. The export is **read-only** on StoryGraph and **never raises into the sync**. Its outcome goes into `status.json` as `kim.to_read_export`, which `write_status` carries over so the hourly write cannot reset it. `exports/` (0700) is bind-mounted into `goodreads-kim` and `goodreads-kim-mfa` only, and it is where the export runs. Manual run: `docker compose run --rm goodreads-kim python -m storygraph.to_read_export --profile kim --force`. A full read of 803 books takes about 4 minutes
- **Read export for reading-cards** (`goodreads/read_export.py`, added 2026-11-07; ruled in katana-fleet's round table `round-table/2026-11-07-reading-cards/`, D2, A1, A2, A10). reading-cards draws a weekly card of the books Kim finished and reads only the file this writes. It runs **inside the hourly sync's own Goodreads browser**, in `_run`, right after `fetch_read_books` has opened the read shelf (newest first) and before the loop moves to review pages, and only on `--apply` runs. It reads the list rows already on screen (the list view carries title, author, pages, start and read dates and the cover, and her rating as the stars widget's `data-rating`, in half stars: `4.0`, `3.5`; confirmed 2026-11-07), so the list normally costs no page load. It visits a book's page only the first time it sees that book, for its genres (the links in the page's `[data-testid=genresList]`, never the header's Browse menu, which links into `/genres/` on every page; at most 5, lower-cased; probed 2026-11-07), cached in `exports/.genre-cache.json`. **Every navigation goes through `Budget`: at most 10 per export, at least 3 s apart; going over keeps the last good file** (genres fetched so far stay cached). It is due on the Monday route (newest success before this week's Monday 00:00 America/New_York, which is the Sunday 21:00 PT run; at most 3 attempts per week) or the daily route (newest success over 20 h old). **One 3-hour cooldown after a failure applies to both** (`goodreads/read_schedule.py`). It publishes `exports/<profile>-read.json` (`{schema: goodreads-read/1, profile, scraped_at, complete, coverage_from, exhausted, oldest_date_read, navigations, books: [{gr_book_id, review_id, title, title_full, author, series, rating, pages, date_started, date_read, cover_url, genres}]}`) **only** if the walk is provably complete back to `coverage_from`, which is 21 days before that Monday: dates descending, every date recognised, and either a row older than the cutoff or a verified end of shelf matching the printed count (`goodreads/read_parse.check_complete`). Month-only dates and `not set` rows are treated as undated, not as failures. Same file rules as the To-Read export: 0600, `.new` then rename, chowned to the owner of `exports/`, never raising into the sync. Its outcome is in `status.json` as `kim.read_export` (`last_success`, `last_attempt`, `last_status`, `anchor`, `attempts_for_anchor`, `error`, `navigations`); `write_status` carries over every block in `status.EXPORT_KEYS`. Manual run (reads Goodreads only): `docker compose run --rm goodreads-kim python -m goodreads.read_export --profile kim --force`. Tests: `python -m pytest tests -q` (offline; `test_runner_hook.py` needs Playwright installed and skips without it)
- **Saved sessions are owner-only.** `storygraph/state/.storygraph_state_*.json` and `goodreads/state/.goodreads_state_*.json` are logins. They are `chmod 0600` whenever they are saved, and the Goodreads one also whenever it is loaded. They were 0644 until 2026-10-19
- **Failures are recorded, not swallowed.** Both entrypoints (`run` in `goodreads/runner.py`, `main` in `runner.py`) wrap the real work (`_run`) in try/except and call `write_failure_status` (`status.py`), which appends `RUN FAILED` + traceback to the run log and writes `"status": "failed"` with the error to `status.json`, then re-raises so the cron script exits non-zero. Before this, a crash left `status.json` frozen at the last good run and the traceback went to cron's discarded stderr — a dead sync was indistinguishable from one that hadn't run yet (a stale StoryGraph password went unnoticed for ~19 hours)
- A StoryGraph password change invalidates the saved session in `storygraph/state/.storygraph_state_{profile}.json`, so the next run falls back to the login form. Update `storygraph_password` in `profiles/{profile}.json` — no rebuild needed, `profiles/` is a read-only bind mount. `ensure_logged_in` (`flows/login_flow.py`) raises a plain "StoryGraph login failed … check storygraph_password" error when the email field is still on screen after submitting, instead of a bare Playwright assertion
- `storygraph/runner_api.py` exposes `storygraph_session()` context manager for browser lifecycle
- StoryGraph search has quirks with `&`, `,`/parentheticals, and `:` subtitles (e.g. `Allegiance: Star Wars Legends` returns nothing) — `search_book_with_fallbacks` (`runner_api.py`) retries with progressively stripped queries before giving up. Both `update_books_read` (Goodreads) and `update_books_progress` (Audible) go through it, so the quirk handling lives in one place
- Author matching in `_token_candidates` (`navigate_flow.py`) accepts either a shared name token *or* identical space-free forms via `compact()` — Goodreads' `J, MK` normalizes to `MK J` while StoryGraph lists `MKJ`, which no shared token can bridge. Equality of the compact form only; substring matching would make a bare initial match every author
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
