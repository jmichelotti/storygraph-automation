# StoryGraphAutomation

Automates syncing reading activity into StoryGraph via Playwright browser automation.

## Architecture — Docker

Everything runs in Docker containers. One image, three services via `docker-compose.yml`:

| Service | Purpose | Lifecycle |
|---------|---------|-----------|
| `dashboard` | FastAPI JSON status API on `127.0.0.1:1200` | Long-lived (`restart: unless-stopped`) |
| `goodreads-kim` | Goodreads -> StoryGraph sync (Kim) | One-shot, fired by Task Scheduler |
| `audible-justin` | Audible -> StoryGraph sync (Justin) | One-shot, fired by Task Scheduler |

Xvfb provides a virtual display inside the container, so the existing `headless=False` code works unchanged.

### Task Scheduler commands

Replace the old `python ...` commands with:
```
docker compose -f C:\dev\StoryGraphAutomation\docker-compose.yml run --rm goodreads-kim
docker compose -f C:\dev\StoryGraphAutomation\docker-compose.yml run --rm audible-justin
```
- Kim: every hour on the hour
- Justin: 11:55 AM and 11:55 PM daily
- Task Scheduler can now use "Run whether user is logged on or not"

### Dashboard

```bash
curl http://localhost:1200/status    # JSON: last run, next run, per-profile state
curl http://localhost:1200/healthz   # health check
```
Start: `docker compose up -d dashboard`

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
   cp -r "$LOCALAPPDATA/Audible/." audible-config/
   ```
3. Start the dashboard: `docker compose up -d dashboard`
4. Test a dry run: `docker compose run --rm goodreads-kim python -m goodreads --profile kim`

## Key conventions

- Credentials live in `profiles/{name}.json` (not committed). Never hardcode credentials.
- Audible CLI auth: `audible-config/` (bind-mounted, not committed). `AUDIBLE_CONFIG_DIR` env var points to it.
- Browser session state: `goodreads/state/` and `storygraph/state/`
- Sync state (processed book IDs): `goodreads/state/state_{profile}.json` and `storygraph/state/sync_{profile}.json`
- Logs: `logs/goodreads/{profile}.log` and `logs/runner/{profile}.log` (append-only, read from tail)
- `storygraph/runner_api.py` exposes `storygraph_session()` context manager for browser lifecycle
- StoryGraph search has known quirks with `&` and `,` in queries — see fallback logic in `runner_api.py`
- Schedule cadences for the dashboard live in `dashboard/schedules.yml`

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
