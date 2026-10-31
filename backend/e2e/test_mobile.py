import pytest
from playwright.sync_api import Browser, expect

PHONE = {"viewport": {"width": 412, "height": 915}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2.6}


@pytest.mark.parametrize("path", ["/", "/predictor", "/colleges", "/neet", "/register"])
def test_no_horizontal_scrolling_on_phones(browser: Browser, base_url: str, path: str):
    page = browser.new_context(base_url=base_url, **PHONE).new_page()
    page.goto(path)
    expect(page.get_by_text("NEET Compass gives guidance, not guarantees.")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0
