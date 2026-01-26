from playwright.sync_api import Page, expect
from storygraph.pages.login_page import LoginPage


def ensure_logged_in(page: Page, email: str, password: str) -> None:
    """
    Ensure the user is logged into StoryGraph.

    - Reuses existing session if present (via storage_state)
    - Falls back to login if session is missing or expired
    """

    page.goto("https://app.thestorygraph.com/users/sign_in", wait_until="domcontentloaded")

    # Strong, unique login-page indicators
    login_form = page.locator("form#new_user")
    email_input = page.locator('input[name="user[email]"]')

    is_login_page = (
        "sign in | the storygraph" in page.title().lower()
        or login_form.count() > 0
        or email_input.count() > 0
    )

    if is_login_page:
        print(" Login required — performing login")

        login_page = LoginPage(page)
        login_page.goto()
        login_page.login(email, password)

        print("GOOD! Login successful")
    else:
        print("GOOD! Existing session detected — skipping login")
