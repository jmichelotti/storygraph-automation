from datetime import date
from playwright.sync_api import Page, expect


def _parse_iso(d: str) -> tuple[str, str, str]:
    """
    '2026-01-18' → ('18', '1', '2026')
    """
    y, m, d = d.split("-")
    return d.lstrip("0"), m.lstrip("0"), y


def set_read_dates(
    page: Page,
    start_date: str | None,
    finish_date: str | None,
) -> None:
    # Small pause for React transition
    page.wait_for_timeout(1000)

    # Click the edit (pencil) link
    edit_link = page.locator(
        "a[href*='/edit-read-instance-from-book']",
        has_text="No read date",
    ).first

    expect(edit_link).to_be_visible(timeout=20_000)
    edit_link.click()
    print("GOOD! Opened read dates editor")

    # Multiple identical forms may exist — grab the visible one
    forms = page.locator("form.edit_read_instance")
    form = forms.filter(has_text="Start date").first
    expect(form).to_be_visible(timeout=10_000)

    print("GOOD! Read dates form visible")

    def set_start(value: str):
        d = date.fromisoformat(value)
        form.locator(
            "select[name='read_instance[start_day]']"
        ).select_option(str(d.day))
        form.locator(
            "select[name='read_instance[start_month]']"
        ).select_option(str(d.month))
        form.locator(
            "select[name='read_instance[start_year]']"
        ).select_option(str(d.year))
        print(f"GOOD! Set start date → {value}")

    def set_finish(value: str):
        d = date.fromisoformat(value)
        form.locator(
            "select[name='read_instance[day]']"
        ).select_option(str(d.day))
        form.locator(
            "select[name='read_instance[month]']"
        ).select_option(str(d.month))
        form.locator(
            "select[name='read_instance[year]']"
        ).select_option(str(d.year))
        print(f"GOOD! Set finish date → {value}")

    if start_date:
        set_start(start_date)

    if finish_date:
        set_finish(finish_date)

    # Save
    form.locator("input[type='submit'][value='Update']").click()
    print("GOOD! Saved read dates")
