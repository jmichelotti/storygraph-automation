import time
from pathlib import Path
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)
from profiles.load_profile import load_profile

GOODREADS_BASE_URL = "https://www.goodreads.com"
GOODREADS_LOGIN = f"{GOODREADS_BASE_URL}/user/sign_in"


def get_state_file(profile: str) -> Path:
    state_dir = Path("goodreads/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f".goodreads_state_{profile}.json"


def get_browser(playwright, profile: str, headless=False):
    state = get_state_file(profile)

    browser = playwright.chromium.launch(headless=headless)

    context = browser.new_context(
        storage_state=state if state.exists() else None
    )

    return browser, context


def _goto_with_retry(page, url, retries=3, wait_until="domcontentloaded", timeout=60_000):
    """
    Navigate with retries and exponential backoff.

    Goodreads' bot mitigation answers a burst of runs by aborting the
    navigation outright (net::ERR_ABORTED), which arrives as a plain Playwright
    Error rather than a timeout — so it used to skip the retry loop entirely and
    kill the run in about a second. Both failure modes are transient, so retry
    on any navigation error and back off between attempts instead of hammering.
    """
    delay = 10

    for attempt in range(retries):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            if attempt == retries - 1:
                raise
            reason = str(exc).splitlines()[0]
            print(
                f"Navigation failed (attempt {attempt + 1}/{retries}): {reason} "
                f"— retrying in {delay}s..."
            )
            time.sleep(delay)
            delay *= 2


def ensure_logged_in(page, context, profile: str):
    creds = load_profile(profile)

    email = creds["goodreads_email"]
    password = creds["goodreads_password"]

    _goto_with_retry(page, GOODREADS_BASE_URL)

    # Already logged in?
    if page.locator("a[href*='/review/list']").count() > 0:
        print("GOOD! Existing Goodreads session detected")
        return

    print(f"Logging into Goodreads ({profile})...")
    _goto_with_retry(page, GOODREADS_LOGIN)

    # 1️⃣ Wait for "Sign in with email" button
    sign_in_with_email = page.locator(
        "a:has(button.authPortalSignInButton)"
    )
    sign_in_with_email.wait_for(timeout=30_000)
    sign_in_with_email.click()

    # 2️⃣ Amazon login fields
    page.wait_for_selector("#ap_email", timeout=30_000)
    page.wait_for_selector("#ap_password", timeout=30_000)

    # 3️⃣ Fill credentials
    page.fill("#ap_email", email)
    page.fill("#ap_password", password)

    # 4️⃣ Submit
    page.click("#signInSubmit")

    # 5️⃣ Wait for redirect
    try:
        page.wait_for_url(f"{GOODREADS_BASE_URL}/**", timeout=60_000)
    except PlaywrightTimeoutError:
        raise RuntimeError("Goodreads login may have failed")

    # 6️⃣ Verify login
    if page.locator("a[href*='/review/list']").count() == 0:
        raise RuntimeError("Goodreads login did not complete successfully")

    # 7️⃣ Persist session
    context.storage_state(path=get_state_file(profile))
    print("GOOD! Logged in and saved Goodreads session state")
