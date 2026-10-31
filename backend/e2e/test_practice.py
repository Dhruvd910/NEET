import re

from playwright.sync_api import Page, expect

from .conftest import new_student


def test_exam_day_to_scorecard(page: Page):
    new_student(page)
    page.goto("/practice")
    expect(page.get_by_text("Fresh questions waiting for you")).to_be_visible()
    page.get_by_role("link", name=re.compile("Mini NEET mock")).click()
    page.get_by_label("Questions per section").select_option("5")
    page.get_by_label(re.compile("Strict OMR mode")).check()
    page.get_by_role("button", name="Prepare my paper").click()

    # 1. Admit card: the clock has not started yet.
    expect(page.get_by_role("heading", name="Admit card")).to_be_visible()
    roll = page.locator("dd.font-mono").first.inner_text().strip()
    assert re.fullmatch(r"\d{10}", roll)
    page.get_by_role("link", name="Continue to instructions").click()
    # 2. Instructions
    expect(page.get_by_role("heading", name=re.compile("Important instructions to candidates", re.I))).to_be_visible()
    page.get_by_label("I have read and understood the instructions.").check()
    page.get_by_role("button", name=re.compile("Fill OMR particulars")).click()
    # 3. OMR particulars must match the admit card and the booklet code.
    code = page.get_by_text(re.compile(r"^[QRS][1-4]$")).first.inner_text().strip()
    page.get_by_placeholder("10 digits").fill("1234567890")
    page.get_by_role("radio", name=code[0], exact=True).check(force=True)
    page.get_by_role("radio", name=code[1], exact=True).check(force=True)
    page.get_by_label(re.compile("Use full screen")).uncheck()
    page.get_by_role("button", name="Break the seal and begin").click()
    expect(page.get_by_role("alert")).to_contain_text("doesn't match your admit card")
    page.get_by_placeholder("10 digits").fill(roll)
    page.get_by_role("button", name="Break the seal and begin").click()

    # The exam room: booklet, OMR sheet, timer.
    expect(page.get_by_role("timer")).to_have_text(re.compile(r"(19|20):\d\d"))
    expect(page.get_by_text(f"Booklet {code}")).to_be_visible()
    page.get_by_role("button", name="Question 1, option 2").click()
    expect(page.get_by_role("button", name="Question 1, option 2")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Question 1, option 3").click()  # strict mode: no change allowed
    expect(page.get_by_text(re.compile("a filled bubble cannot be changed")).first).to_be_visible()
    page.get_by_role("tab", name=re.compile("Zoology")).click()
    expect(page.locator("#qnum")).to_have_text("16.")
    page.get_by_role("button", name="Rough work").click()
    expect(page.get_by_role("dialog", name="Rough work")).to_be_visible()
    page.get_by_role("button", name="Close").click()

    page.once("dialog", lambda d: d.accept())  # "Hand in your answer sheet?"
    page.get_by_role("button", name="Submit").click()
    expect(page.get_by_text("Scorecard")).to_be_visible()
    expect(page.get_by_role("heading", name="By section")).to_be_visible()
    page.get_by_role("link", name="all", exact=True).click()
    expect(page.get_by_text(re.compile("✓ correct")).first).to_be_visible()
    page.get_by_text("Report a problem", exact=True).first.click()
    page.get_by_role("button", name="Send").first.click()
    expect(page.get_by_text(re.compile("Thanks — reported"))).to_be_visible()


def test_class_based_study_plan(page: Page):
    new_student(page)
    page.goto("/study-plan")
    page.get_by_label("Your class").select_option("11")
    page.get_by_role("button", name="Build my plan").click()
    expect(page.get_by_text(re.compile(r"Class 11 · NEET on .* \(estimated\)"))).to_be_visible()
    expect(page.get_by_role("heading", name=re.compile("This week"))).to_be_visible()
    first = page.get_by_role("checkbox", name=re.compile('Mark "Learn: ')).first
    first.check()
    expect(page.get_by_role("checkbox", name=re.compile('Mark "Learn: ')).first).to_be_checked()
    page.get_by_role("link", name=re.compile(r"^Zoology")).click()
    expect(page.get_by_label("Status of Animal Kingdom")).to_be_visible()
