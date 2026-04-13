# StoryGraphAutomation

Automates syncing reading activity into StoryGraph via Playwright browser automation.

## Workflows

Two scheduled jobs run via Windows Task Scheduler (working directory: `C:\dev\StoryGraphAutomation`):

1. **Goodreads -> StoryGraph (Kim):** `python -m goodreads --profile kim --apply`
   - Scrapes Goodreads read shelf, marks matched books as "read" on StoryGraph with dates
   - `--apply` required for real writes; default is dry-run

2. **Audible -> StoryGraph (Justin):** `python runner.py --profile justin`
   - Exports Audible library via CLI, diffs progress, updates StoryGraph percentages
   - Always applies (no dry-run mode)

## Key conventions

- Credentials live in `profiles/{name}.json` (not committed). Never hardcode credentials.
- Browser session state: `goodreads/state/` and `storygraph/state/`
- Sync state (processed book IDs): `goodreads/state/state_{profile}.json` and `storygraph/state/sync_{profile}.json`
- Logs: `logs/goodreads/{profile}.log` and `logs/runner/{profile}.log` (append-only, read from tail)
- `storygraph/runner_api.py` exposes `storygraph_session()` context manager for browser lifecycle
- StoryGraph search has known quirks with `&` and `,` in queries — see fallback logic in `runner_api.py`

## Testing changes

Run both pipelines to verify:
```
python -m goodreads --profile kim          # dry-run (safe)
python runner.py --profile justin          # diffs only if no changes
```
