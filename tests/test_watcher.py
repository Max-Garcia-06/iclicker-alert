from unittest import mock

import pytest

import watcher
from watcher import PollState, load_config

TOPIC = "iclicker-0123456789abcdef0123"


def write(tmp_path, body):
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_load_config_fills_defaults(tmp_path):
    cfg = load_config(write(tmp_path, f'ntfy_topic = "{TOPIC}"\n'))
    assert cfg["ntfy_topic"] == TOPIC
    assert cfg["interval_s"] == 2.0
    assert cfg["url"] == "https://student.iclicker.com/"
    assert cfg["match"] == "iclicker.com"
    assert cfg["imessage_to"] == ""
    assert cfg["channel"] == ""


def test_load_config_missing_file(tmp_path):
    with pytest.raises(SystemExit, match="config.example.toml"):
        load_config(tmp_path / "config.toml")


@pytest.mark.parametrize("topic", ["iclicker-REPLACE_ME", "iclicker", "short-topic-123"])
def test_load_config_rejects_guessable_topic(tmp_path, topic):
    with pytest.raises(SystemExit, match="ntfy_topic"):
        load_config(write(tmp_path, f'ntfy_topic = "{topic}"\n'))


def test_load_config_allows_empty_topic(tmp_path):
    assert load_config(write(tmp_path, 'ntfy_topic = ""\n'))["ntfy_topic"] == ""


def feed(states):
    s = PollState()
    return [s.update(x) for x in states]


def test_state_fires_once_per_open():
    assert feed([False, True, True, True]) == [False, True, False, False]


def test_state_ignores_single_tick_flicker():
    assert feed([True, False, True]) == [True, False, False]


def test_state_rearms_after_two_closed_ticks():
    assert feed([True, False, False, True]) == [True, False, False, True]


def test_main_test_alert_reports_results(tmp_path, capsys):
    cfg_path = write(tmp_path, f'ntfy_topic = "{TOPIC}"\n')
    with mock.patch("watcher.fire_all", return_value={"ntfy": True, "mac": False}):
        code = watcher.main(["--test-alert", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert "ntfy: ok" in out
    assert "mac: FAILED" in out
    assert code == 1

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from watcher import Recorder, find_pages, run_loop

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ctx(tmp_path):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(tmp_path / "profile"), headless=True)
        yield context
        try:
            context.close()
        except Exception:
            pass


def loop_cfg():
    return {**watcher.DEFAULTS, "interval_s": 0.25, "match": "fake_class.html"}


def test_run_loop_alerts_once_per_poll_and_rearms(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto((FIXTURES / "fake_class.html").as_uri())
    calls = []
    run_loop(ctx, loop_cfg(), alert=lambda cfg: calls.append(time.monotonic()), max_ticks=24)
    time.sleep(0.2)  # let alert threads finish
    assert len(calls) == 2


def test_find_pages_ignores_other_pages(ctx):
    other = ctx.pages[0] if ctx.pages else ctx.new_page()
    other.goto((FIXTURES / "no_poll.html").as_uri())
    assert find_pages(ctx, "fake_class.html") == []
    target = ctx.new_page()
    target.goto((FIXTURES / "fake_class.html").as_uri())
    assert find_pages(ctx, "fake_class.html") == [target]


def test_find_pages_ignores_match_in_query_string(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto((FIXTURES / "no_poll.html").as_uri() + "?redirect=fake_class.html")
    assert find_pages(ctx, "fake_class.html") == []


def test_run_loop_exits_when_all_pages_closed(ctx):
    for pg in list(ctx.pages):
        pg.close()
    start = time.monotonic()
    run_loop(ctx, loop_cfg(), alert=lambda cfg: None, max_ticks=None)
    assert time.monotonic() - start < 2


def test_recorder_saves_only_on_text_change(ctx, tmp_path):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    rec = Recorder(tmp_path / "rec")
    page.set_content("<p>one</p>")
    assert rec.maybe_save(page, {"open": False, "reason": "x"}) is True
    assert rec.maybe_save(page, {"open": False, "reason": "x"}) is False
    page.set_content("<p>two</p>")
    assert rec.maybe_save(page, {"open": True, "reason": "y"}) is True
    files = sorted(p.suffix for p in (tmp_path / "rec").iterdir() if p.name != "log.jsonl")
    assert files == [".html", ".html", ".png", ".png"]
    lines = (tmp_path / "rec" / "log.jsonl").read_text().splitlines()
    assert [json.loads(l)["detect"]["open"] for l in lines] == [False, True]


class FakeCtx:
    def __init__(self):
        self.pages = []
        self.events = []

    def on(self, event, handler):
        self.events.append(event)


def test_run_loop_leaves_page_dialogs_for_user():
    # With no "dialog" listener, Playwright auto-dismisses alert/confirm, acting on iClicker.
    ctx = FakeCtx()
    run_loop(ctx, loop_cfg(), alert=lambda cfg: None, max_ticks=1)
    assert "dialog" in ctx.events


def test_run_loop_watches_every_matching_tab(ctx):
    first = ctx.pages[0] if ctx.pages else ctx.new_page()
    first.goto((FIXTURES / "poll.html").as_uri())
    second = ctx.new_page()
    second.goto((FIXTURES / "no_poll.html").as_uri())
    calls = []
    run_loop(ctx, {**loop_cfg(), "match": "fixtures/"}, alert=calls.append, max_ticks=2)
    time.sleep(0.2)
    assert len(calls) == 1


class BrokenRecorder:
    def maybe_save(self, page, result):
        raise OSError(28, "No space left on device")


def test_run_loop_alerts_even_when_recorder_fails(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto((FIXTURES / "poll.html").as_uri())
    calls = []
    run_loop(ctx, {**loop_cfg(), "match": "poll.html"}, alert=calls.append,
             recorder=BrokenRecorder(), max_ticks=2)
    time.sleep(0.2)
    assert len(calls) == 1


def test_recorder_rate_limits_ticking_text(ctx, tmp_path):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    rec = Recorder(tmp_path / "rec")
    page.set_content("<p>0:30</p>")
    assert rec.maybe_save(page, {"open": True, "reason": "x"}) is True
    page.set_content("<p>0:28</p>")
    assert rec.maybe_save(page, {"open": True, "reason": "x"}) is False  # countdown tick, same state
    page.set_content("<p>closed</p>")
    assert rec.maybe_save(page, {"open": False, "reason": "x"}) is True  # state change always saves
