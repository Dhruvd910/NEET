import re

from playwright.sync_api import Browser, Page, expect

from .conftest import BASE, PASSWORD, latest_email, sign_in


def test_landing_page_carries_the_disclaimer(page: Page):
    page.goto("/")
    expect(page.get_by_text("NEET Compass gives guidance, not guarantees.")).to_be_visible()


def test_anonymous_predictor_groups_demo_results_without_probabilities(page: Page):
    page.goto("/predictor")
    page.get_by_label("All India Rank").fill("9000")
    page.get_by_role("button", name="Show historical matches").click()
    expect(page.get_by_role("heading", name=re.compile(r"Stronger historical fit|Possible \/ uncertain|Ambitious")).first).to_be_visible()
    expect(page.get_by_text("DEMO", exact=False).first).to_be_visible()
    expect(page.locator("body")).not_to_contain_text(re.compile(r"\d+\s?% chance|guaranteed seat|safe college", re.I))


def test_college_page_shows_fees_with_academic_year_and_demo_status(page: Page):
    page.goto("/colleges")
    page.get_by_role("link", name="Full details").first.click()
    page.get_by_role("tab", name="Fees & cost").click()
    expect(page.get_by_text(re.compile(r"20\d\d-\d\d")).first).to_be_visible()
    expect(page.get_by_text("DEMO data — not real").first).to_be_visible()


def test_compare_two_colleges_from_the_list(page: Page):
    page.goto("/colleges")
    buttons = page.get_by_role("button", name="+ Compare")
    buttons.nth(0).click()
    buttons.nth(0).click()  # the first button now reads "✓ In compare", so nth(0) is the next college
    page.goto("/compare")
    expect(page.get_by_role("heading", name="What stands out for your priorities")).to_be_visible()
    page.get_by_label("Larger attached-hospital bed capacity").check()
    expect(page).to_have_url(re.compile(r"prio=clinical"))


def test_signed_in_student_can_use_the_assistant(page: Page):
    sign_in(page, "student@demo.test")
    page.goto("/assistant")
    page.get_by_placeholder(re.compile("Ask anything about NEET-UG")).fill("What documents do I need for counselling?")
    page.get_by_role("button", name="Send message").click()
    expect(page).to_have_url(re.compile(r"/assistant\?chat=\d+"), timeout=20_000)
    expect(page.locator("body")).not_to_contain_text("CSRF")
    expect(page.get_by_text("Sources", exact=True).last).to_be_visible()


def test_minor_stays_locked_until_the_guardian_consents(page: Page, browser: Browser):
    page.goto("/register")
    page.get_by_label("Email", exact=True).fill(f"minor-{id(page)}@example.test")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_label("Yes").check()
    page.get_by_label(re.compile("guardian's email", re.I)).fill("parent@example.test")
    page.get_by_label("I have read the privacy notice").check()
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_text("Waiting for your parent or guardian").first).to_be_visible()

    mail = latest_email()
    assert "To: parent@example.test" in mail
    link = re.search(r"https?://\S+guardian-consent\?token=\S+", mail).group(0)
    guardian = browser.new_context().new_page()  # the parent's own browser
    guardian.goto(re.sub(r"^https?://[^/]+", BASE, link))
    expect(guardian.get_by_role("heading", name="Parent or guardian consent")).to_be_visible()
    guardian.get_by_label("Your full name").fill("Parent Name")
    guardian.get_by_label("Relationship to the student").select_option("mother")
    guardian.get_by_label(re.compile("I am this student's parent or legal guardian")).check()
    guardian.get_by_role("button", name="I give consent").click()
    expect(guardian.get_by_text("Thank you — consent recorded")).to_be_visible()

    page.reload()
    expect(page.get_by_text("Waiting for your parent or guardian")).to_have_count(0)


def test_admin_sees_readiness_and_students_do_not_see_admin(page: Page):
    sign_in(page, "student@demo.test")
    expect(page.get_by_role("menuitem", name="Admin")).to_have_count(0)
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("link", name="Sign in")).to_be_visible()

    sign_in(page, "admin@demo.test")
    page.goto("/admin")
    expect(page.get_by_role("heading", name="Go-live readiness")).to_be_visible()
    expect(page.get_by_text("DPDP Act 2023 legal review completed")).to_be_visible()
    page.get_by_role("tab", name="Eligibility rules").click()
    expect(page.get_by_role("heading", name=re.compile("Missing rules"))).to_be_visible()
