from datetime import date
from playwright.sync_api import Page, TimeoutError, expect


def set_read_dates(
    page: Page,
    start_date: str | None,
    finish_date: str | None,
) -> None:
    """Fill in the book's read dates, only setting dates that are currently
    empty.

    Existing dates (e.g. ones the reader already entered by hand) are left
    untouched — we only fill the blanks. Works whether the book was just
    marked read (link reads "No read date") or was already read with some
    dates (link reads "Finished ..."). If no read-date editor can be found,
    it logs and returns rather than raising, so one book can't abort the run.
    """
    # Small pause for React transition
    page.wait_for_timeout(1000)

    # The read-instance edit link reads "No read date" on a freshly marked
    # book, or "Finished <date>" once it has any date — so match on the link
    # itself (the visible one), not on a specific label.
    edit_link = page.locator(
        "a[href*='/edit-read-instance-from-book']:visible"
    ).first

    try:
        edit_link.wait_for(state="visible", timeout=20_000)
    except TimeoutError:
        print("INFO! No read-date editor found — leaving read dates unchanged")
        return

    edit_link.click()
    print("GOOD! Opened read dates editor")

    # Multiple identical forms may exist — grab the visible one
    forms = page.locator("form.edit_read_instance")
    form = forms.filter(has_text="Start date").first
    expect(form).to_be_visible(timeout=10_000)

    print("GOOD! Read dates form visible")

    changed = False

    def fill_if_empty(value, day_sel, month_sel, year_sel, label):
        """Set the date only if the field is currently blank."""
        nonlocal changed
        if not value:
            return
        day_loc = form.locator(day_sel)
        if day_loc.input_value():
            print(f"INFO! {label} date already set — leaving as-is")
            return
        d = date.fromisoformat(value)
        day_loc.select_option(str(d.day))
        form.locator(month_sel).select_option(str(d.month))
        form.locator(year_sel).select_option(str(d.year))
        changed = True
        print(f"GOOD! Set {label} date -> {value}")

    fill_if_empty(
        start_date,
        "select[name='read_instance[start_day]']",
        "select[name='read_instance[start_month]']",
        "select[name='read_instance[start_year]']",
        "start",
    )
    fill_if_empty(
        finish_date,
        "select[name='read_instance[day]']",
        "select[name='read_instance[month]']",
        "select[name='read_instance[year]']",
        "finish",
    )

    if not changed:
        print("INFO! Read dates already complete — nothing to update")
        return

    # Save — wait for the POST to complete before the browser is closed
    form.locator("input[type='submit'][value='Update']").click()
    page.wait_for_load_state("load")
    print("GOOD! Saved read dates")
