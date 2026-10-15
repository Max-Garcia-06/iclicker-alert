from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from watcher import DETECT_JS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


def detect(page, name):
    page.goto((FIXTURES / name).as_uri())
    return page.evaluate(DETECT_JS)


def test_visible_answer_buttons_mean_open(page):
    result = detect(page, "poll.html")
    assert result["open"] is True
    assert "A,B,C,D,E" in result["reason"]


def test_hidden_buttons_and_single_letter_mean_closed(page):
    result = detect(page, "no_poll.html")
    assert result["open"] is False


def test_buttons_appearing_later_flip_to_open(page):
    page.goto((FIXTURES / "no_poll.html").as_uri())
    assert page.evaluate(DETECT_JS)["open"] is False
    page.evaluate("""() => {
        for (const l of ["B", "C"]) {
            const b = document.createElement("button");
            b.textContent = l;
            document.body.appendChild(b);
        }
    }""")
    assert page.evaluate(DETECT_JS)["open"] is True
