import time
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from goodreads.config import GOODREADS_BASE_URL
from profiles.load_profile import load_profile

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
    for attempt in range(retries):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except PlaywrightTimeoutError:
            if attempt == retries - 1:
                raise
            print(f"Navigation timeout (attempt {attempt + 1}/{retries}), retrying...")
            time.sleep(2)


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
