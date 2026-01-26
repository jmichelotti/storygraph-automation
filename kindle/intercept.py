import json
from playwright.sync_api import Page

def intercept_kindle_api(page: Page, captured: list[dict]):
    def handle_response(response):
        url = response.url

        # Kindle Web APIs always hit read.amazon.com
        if "read.amazon.com" not in url:
            return

        if response.request.resource_type != "xhr":
            return

        print(f"[XHR] {url}")

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return

        try:
            data = response.json()
        except Exception:
            print(f"⚠️ Failed JSON parse: {url}")
            return

        captured.append({
            "url": url,
            "data": data,
        })

    page.on("response", handle_response)
