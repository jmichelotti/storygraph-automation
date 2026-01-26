from pathlib import Path
from playwright.sync_api import Page

def ensure_logged_in(
    page: Page,
    email: str,
    password: str,
):
    page.goto("https://read.amazon.com", wait_until="domcontentloaded")

    # Already logged in
    if page.locator("text=Kindle Cloud Reader").count() > 0:
        print("OK Existing Kindle session detected")
        return

    print("Login required — signing in")

    page.locator("input[name='email']").fill(email)
    page.locator("input#continue").click()

    page.locator("input[name='password']").fill(password)
    page.locator("input#signInSubmit").click()

    # Allow manual MFA if needed
    page.wait_for_timeout(20000)

    print("Login completed (or awaiting MFA)")
