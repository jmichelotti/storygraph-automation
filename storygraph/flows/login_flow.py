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

        try:
            login_page.login(email, password)
        except Exception as exc:
            # LoginPage.login asserts the email field is gone after submitting.
            # If it's still on the page the credentials were rejected — say so,
            # because the raw Playwright assertion ("expected count 0") gives no
            # hint that the stored password went stale. A password change also
            # invalidates the saved session, so this is the first thing to hit.
            if page.locator('input[name="user[email]"]').count() > 0:
                raise RuntimeError(
                    f"StoryGraph login failed for {email} — check "
                    f"storygraph_password in profiles/*.json"
                ) from exc
            raise

        print("GOOD! Login successful")
    else:
        print("GOOD! Existing session detected — skipping login")
