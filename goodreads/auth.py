from pathlib import Path
import json
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from goodreads.config import GOODREADS_BASE_URL

GOODREADS_LOGIN = f"{GOODREADS_BASE_URL}/user/sign_in"


def get_state_file(profile: str) -> Path:
    return Path(f".goodreads_state_{profile}.json")


def load_profile(profile: str) -> dict:
    path = Path("profiles") / f"{profile}.json"
    if not path.exists():
        raise RuntimeError(f"Profile not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_browser(playwright, profile: str, headless=False):
    state = get_state_file(profile)

    browser = playwright.chromium.launch(headless=headless)

    context = browser.new_context(
        storage_state=state if state.exists() else None
    )

    return browser, context


def ensure_logged_in(page, context, profile: str):
    creds = load_profile(profile)

    email = creds["goodreads_email"]
    password = creds["goodreads_password"]

    page.goto(GOODREADS_BASE_URL)

    # Already logged in?
    if page.locator("a[href*='/review/list']").count() > 0:
        print("GOOD! Existing Goodreads session detected")
        return

    print(f"Logging into Goodreads ({profile})...")
    page.goto(GOODREADS_LOGIN)

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
