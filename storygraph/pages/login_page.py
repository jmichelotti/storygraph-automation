from playwright.sync_api import Page, expect

class LoginPage:
    def __init__(self, page: Page):
        self.page = page

        # Keep selectors centralized here
        self.email_input = 'input[name="user[email]"]'
        self.password_input = 'input[name="user[password]"]'

        # StoryGraph uses a <button id="sign-in-btn" type="submit">Sign in</button>
        self.submit_button = "#sign-in-btn"

        # Optional: a safe "you are logged in" indicator
        # We’ll use URL change + disappearance of email field as the main signal.

    def goto(self) -> None:
        self.page.goto("https://app.thestorygraph.com/users/sign_in", wait_until="domcontentloaded")

    def login(self, email: str, password: str) -> None:
        self.page.fill(self.email_input, email)
        self.page.fill(self.password_input, password)

        # Click sign-in (and let navigation happen)
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            self.page.click(self.submit_button)

        # Confirm we're not still on sign-in page (robust, avoids guessing exact destination)
        self.page.wait_for_url("**/app.thestorygraph.com/**", timeout=30000)

        # If login failed, the email input will still be visible.
        # If login succeeded, it should be gone.
        expect(self.page.locator(self.email_input)).to_have_count(0, timeout=15000)
