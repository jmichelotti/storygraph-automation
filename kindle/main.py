from playwright.sync_api import sync_playwright
from pathlib import Path
import os
from dotenv import load_dotenv

from kindle.auth import ensure_logged_in
from kindle.intercept import intercept_kindle_api

load_dotenv()

STATE_DIR = Path("kindle/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)

def get_state_path(profile: str) -> Path:
    return STATE_DIR / f"kindle_state_{profile}.json"


def run(profile: str, headless: bool = True):
    captured: list[dict] = []

    state_path = get_state_path(profile)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        context = (
            browser.new_context(storage_state=state_path)
            if state_path.exists()
            else browser.new_context()
        )

        page = context.new_page()

        # 🔌 Attach interceptor BEFORE navigation
        intercept_kindle_api(page, captured)

        # 🚀 Always go directly to the Kindle library
        page.goto(
            "https://read.amazon.com/kindle-library",
            wait_until="networkidle",
        )

        ensure_logged_in(
            page,       
            os.environ["AMAZON_EMAIL"],
            os.environ["AMAZON_PASSWORD"],
        )

        print("⏳ Waiting for Kindle library or manual auth (login/MFA)...")

        # Wait until we're no longer on an Amazon auth page
        page.wait_for_function(
            """
            () => {
                const url = window.location.href;
                return !url.includes('/ap/signin') && !url.includes('/ap/mfa');
            }
            """,
            timeout=180_000,  # allow time for MFA
        )

        print("✅ Auth flow completed")

        # Now wait for *any* Kindle UI signal
        page.wait_for_function(
            """
            () => {
                return (
                    document.querySelector('.kp-notebook-library') ||
                    document.querySelector('[data-testid]') ||
                    document.body.innerText.includes('Your Library')
                );
            }
            """,
            timeout=60_000,
        )

        print("📚 Kindle library detected")


        # ⏳ Give XHRs time to fire (this is crucial)
        page.wait_for_timeout(20_000)

        # 💾 Save state AFTER everything is loaded
        context.storage_state(path=state_path)
        print(f"✅ Kindle session saved to {state_path}")

        browser.close()

    print(f"Captured {len(captured)} Kindle API responses")
    return captured


if __name__ == "__main__":
    run(profile="justin", headless=False)
