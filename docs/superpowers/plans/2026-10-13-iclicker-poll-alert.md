# iClicker Poll Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Python tool that watches an iClicker tab in a Playwright-launched Chrome window and fires phone push, macOS notification, and iMessage alerts the moment a poll opens.

**Architecture:** `watcher.py` launches a persistent-profile Chromium context, evaluates `detect.js` in the iClicker page every `interval_s`, feeds the result into a `PollState` edge-trigger, and on closed→open calls `alerts.fire_all()` in a background thread. `alerts.py` sends each channel via `subprocess` (`curl` for ntfy, `osascript` for macOS + Messages). Optional `--record` mode saves HTML + screenshot on every page-text change for refining detection later.

**Tech Stack:** Python 3.12 (uv-managed), Playwright (sync API, bundled Chromium), pytest, macOS `osascript`, `curl`, ntfy.sh.

**Spec:** `docs/superpowers/specs/2026-10-13-iclicker-poll-alert-design.md`

## Global Constraints

- Python pinned to 3.12 via `uv python pin 3.12`; runtime dependency `playwright` only; dev dependency `pytest` only.
- Alert text is exactly `iClicker poll open`. Notification/ntfy title is exactly `iClicker`. No question text, no course name in any alert.
- The tool never clicks, types, or submits anything inside iClicker. Only `page.evaluate` (read-only JS), `page.content()`, `page.screenshot()`, and the initial `page.goto(cfg["url"])`.
- iMessage recipient is passed to `osascript` as an argv argument, never interpolated into AppleScript source.
- `config.toml` and `recordings/` are gitignored. Browser profile lives at `~/.iclicker-alert/profile` (outside repo).
- `ntfy_topic` shorter than 20 chars or containing `REPLACE` → refuse to start.
- Every alert channel failure is logged and swallowed; one failing channel never blocks the others.

## Review Focus

1. **Guessable ntfy topic** — user leaves placeholder or picks `iclicker` → anyone could read/spam the topic. Expect: startup refuses with a clear message. Test in Task 3.
2. **Recipient containing quotes / AppleScript syntax** — e.g. `x" & do shell script "rm -rf ~"` → must not execute; must appear only as an argv element. Test in Task 1.
3. **Poll UI flicker** — detection reads open, closed for one tick (re-render), open again → expect exactly one alert. Test in Task 3.
4. **Pre-rendered hidden A–E buttons** — iClicker may keep answer buttons in the DOM with `display:none` between polls → expect closed. Test in Task 2.
5. **User closes the window** — all pages gone → expect loop to exit promptly, not spin forever. Test in Task 4.

---

### Task 1: Project scaffold + alert channels

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.python-version` (via `uv python pin`), `config.example.toml`
- Create: `alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `alerts.MESSAGE: str` = `"iClicker poll open"`
  - `alerts.IMESSAGE_SCRIPT: str` (AppleScript source, takes `recipient`, `msg` from argv)
  - `alerts.ntfy(topic: str) -> None` (raises on failure)
  - `alerts.mac_notify() -> None` (raises on failure)
  - `alerts.imessage(recipient: str) -> None` (raises on failure)
  - `alerts.fire_all(cfg: dict) -> dict[str, bool]` — keys present only for attempted channels (`"ntfy"`, `"mac"`, `"imessage"`); never raises.

- [ ] **Step 1: Scaffold project**

Create `pyproject.toml`:

```toml
[project]
name = "iclicker-alert"
version = "0.1.0"
description = "Alert when an iClicker poll opens"
requires-python = ">=3.12"
dependencies = ["playwright>=1.48"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Create `.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
config.toml
recordings/
```

Create `config.example.toml`:

```toml
# Copy to config.toml and fill in.
# Generate a topic:  python3 -c "import secrets; print('iclicker-' + secrets.token_hex(16))"
# Then subscribe to that topic in the ntfy phone app (ntfy.sh server).
ntfy_topic = "iclicker-REPLACE_ME"

# Your phone number (+1XXXXXXXXXX) or Apple ID email. Empty string = skip iMessage.
imessage_to = ""

interval_s = 2.0
url = "https://student.iclicker.com/"
match = "iclicker.com"

# Set to "chrome" to use your installed Google Chrome if login is blocked in Chromium.
channel = ""
```

Run:

```bash
cd ~/iclicker-alert
uv python pin 3.12
uv sync
uv run playwright install chromium
mkdir -p tests/fixtures
```

Expected: `.python-version` contains `3.12`, `.venv/` created, Chromium downloaded.

- [ ] **Step 2: Write failing tests**

Create `tests/test_alerts.py`:

```python
import subprocess
from unittest import mock

import alerts


def ok(*args, **kwargs):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_ntfy_posts_fixed_message_with_curl():
    with mock.patch("alerts.subprocess.run", side_effect=ok) as run:
        alerts.ntfy("iclicker-abc123abc123abc123")
    argv = run.call_args.args[0]
    assert argv[0] == "curl"
    assert "https://ntfy.sh/iclicker-abc123abc123abc123" == argv[-1]
    assert ["-d", "iClicker poll open"] == argv[argv.index("-d"):argv.index("-d") + 2]
    assert "Priority: high" in argv
    assert "Title: iClicker" in argv
    assert "-f" in argv  # HTTP errors become non-zero exit
    assert run.call_args.kwargs["check"] is True


def test_mac_notify_uses_osascript():
    with mock.patch("alerts.subprocess.run", side_effect=ok) as run:
        alerts.mac_notify()
    argv = run.call_args.args[0]
    assert argv[0] == "osascript"
    assert 'display notification "iClicker poll open" with title "iClicker"' in argv[2]


def test_imessage_passes_recipient_as_argv_not_script_text():
    evil = 'x" & do shell script "touch /tmp/pwned" & "'
    with mock.patch("alerts.subprocess.run", side_effect=ok) as run:
        alerts.imessage(evil)
    argv = run.call_args.args[0]
    assert argv[:3] == ["osascript", "-e", alerts.IMESSAGE_SCRIPT]
    assert argv[3] == evil
    assert argv[4] == "iClicker poll open"
    assert evil not in alerts.IMESSAGE_SCRIPT
    assert "on run argv" in alerts.IMESSAGE_SCRIPT


def test_fire_all_one_failure_does_not_block_others():
    def run(argv, **kwargs):
        if argv[0] == "curl":
            raise subprocess.CalledProcessError(6, argv, stderr="could not resolve host")
        return ok(argv)

    cfg = {"ntfy_topic": "iclicker-abc123abc123abc123", "imessage_to": "+15551234567"}
    with mock.patch("alerts.subprocess.run", side_effect=run) as m:
        results = alerts.fire_all(cfg)
    assert results == {"ntfy": False, "mac": True, "imessage": True}
    assert m.call_count == 3


def test_fire_all_skips_empty_channels():
    with mock.patch("alerts.subprocess.run", side_effect=ok) as m:
        results = alerts.fire_all({"ntfy_topic": "", "imessage_to": ""})
    assert results == {"mac": True}
    assert m.call_count == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: FAIL / collection error with `ModuleNotFoundError: No module named 'alerts'`

- [ ] **Step 4: Implement `alerts.py`**

```python
"""Alert channels: ntfy push, macOS notification, iMessage to self."""
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

MESSAGE = "iClicker poll open"
TITLE = "iClicker"

# Recipient and message come in through argv so user input never becomes script source.
IMESSAGE_SCRIPT = """
on run argv
    set recipient to item 1 of argv
    set msg to item 2 of argv
    tell application "Messages"
        set svc to 1st account whose service type = iMessage
        send msg to participant recipient of svc
    end tell
end run
"""


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, capture_output=True, text=True, timeout=10)


def ntfy(topic: str) -> None:
    _run([
        "curl", "-sS", "-f", "-m", "5",
        "-H", f"Title: {TITLE}",
        "-H", "Priority: high",
        "-H", "Tags: bell",
        "-d", MESSAGE,
        f"https://ntfy.sh/{topic}",
    ])


def mac_notify() -> None:
    _run(["osascript", "-e", f'display notification "{MESSAGE}" with title "{TITLE}"'])


def imessage(recipient: str) -> None:
    _run(["osascript", "-e", IMESSAGE_SCRIPT, recipient, MESSAGE])


def fire_all(cfg: dict) -> dict[str, bool]:
    jobs = {}
    if cfg.get("ntfy_topic"):
        jobs["ntfy"] = lambda: ntfy(cfg["ntfy_topic"])
    else:
        log.info("ntfy skipped: no ntfy_topic")
    jobs["mac"] = mac_notify
    if cfg.get("imessage_to"):
        jobs["imessage"] = lambda: imessage(cfg["imessage_to"])
    else:
        log.info("iMessage skipped: no imessage_to")

    results = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        for name, fut in futures.items():
            try:
                fut.result()
                results[name] = True
            except Exception as e:
                detail = getattr(e, "stderr", "") or e
                log.warning("%s alert failed: %s", name, detail)
                results[name] = False
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore config.example.toml alerts.py tests/test_alerts.py
git commit -m "feat: add alert channels (ntfy, macOS notification, iMessage)"
```

---

### Task 2: Poll detection JS

**Files:**
- Create: `detect.js`
- Create: `watcher.py` (only the `DETECT_JS` loader for now)
- Create: `tests/fixtures/poll.html`, `tests/fixtures/no_poll.html`
- Test: `tests/test_detect.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `detect.js`: a JS arrow-function expression; `page.evaluate(DETECT_JS)` returns `{"open": bool, "reason": str}`.
  - `watcher.ROOT: Path` (repo dir), `watcher.DETECT_JS: str`.

- [ ] **Step 1: Write fixtures**

`tests/fixtures/poll.html`:

```html
<!doctype html>
<html><body>
  <h1>Question 3</h1>
  <div class="answers">
    <button>A</button>
    <button>B</button>
    <button><span>C</span></button>
    <div role="button">D</div>
    <button> E </button>
  </div>
</body></html>
```

`tests/fixtures/no_poll.html`:

```html
<!doctype html>
<html><body>
  <h1>Waiting for your instructor to start a poll</h1>
  <button>Join</button>
  <button>A</button>
  <div style="display:none">
    <button>A</button><button>B</button><button>C</button>
  </div>
  <div style="visibility:hidden">
    <button>D</button><button>E</button>
  </div>
  <button>Add</button>
</body></html>
```

(One visible `A` alone is not a poll; hidden A–E buttons are not a poll; `Add` is not a label.)

- [ ] **Step 2: Write failing tests**

`tests/test_detect.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_detect.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'watcher'`

- [ ] **Step 4: Implement `detect.js` and loader**

`detect.js`:

```js
() => {
  // v1 heuristic: poll is open when >=2 distinct visible answer buttons A-E exist.
  // Replace with an exact rule once --record captures real iClicker pages.
  const LABELS = new Set(["A", "B", "C", "D", "E"]);
  const seen = new Set();
  for (const el of document.querySelectorAll('button, [role="button"]')) {
    const text = (el.innerText || "").trim();
    if (!LABELS.has(text)) continue;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0) continue;
    if (style.visibility === "hidden" || style.display === "none") continue;
    seen.add(text);
  }
  const labels = [...seen].sort();
  return labels.length >= 2
    ? { open: true, reason: `answer buttons: ${labels.join(",")}` }
    : { open: false, reason: `answer buttons: ${labels.length}` };
}
```

`watcher.py`:

```python
"""Watch an iClicker tab and alert when a poll opens."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DETECT_JS = (ROOT / "detect.js").read_text()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_detect.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add detect.js watcher.py tests/test_detect.py tests/fixtures/poll.html tests/fixtures/no_poll.html
git commit -m "feat: add poll detection heuristic"
```

---

### Task 3: Config loading + poll state machine + `--test-alert` CLI

**Files:**
- Modify: `watcher.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Consumes: `alerts.fire_all(cfg) -> dict[str, bool]`, `watcher.ROOT`.
- Produces:
  - `watcher.load_config(path: Path) -> dict` — raises `SystemExit(str)` on missing file or bad topic; fills defaults `interval_s=2.0`, `url="https://student.iclicker.com/"`, `match="iclicker.com"`, `channel=""`, `ntfy_topic=""`, `imessage_to=""`.
  - `watcher.PollState` with `update(is_open: bool) -> bool` (True = fire alert now) and class attr `CLOSE_TICKS = 2`.
  - `watcher.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write failing tests**

`tests/test_watcher.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'PollState' from 'watcher'`

- [ ] **Step 3: Implement**

Replace `watcher.py` with:

```python
"""Watch an iClicker tab and alert when a poll opens."""
import argparse
import logging
import sys
import tomllib
from pathlib import Path

from alerts import fire_all

ROOT = Path(__file__).resolve().parent
DETECT_JS = (ROOT / "detect.js").read_text()

log = logging.getLogger("watcher")

DEFAULTS = {
    "ntfy_topic": "",
    "imessage_to": "",
    "interval_s": 2.0,
    "url": "https://student.iclicker.com/",
    "match": "iclicker.com",
    "channel": "",
}


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing {path}. Copy config.example.toml to config.toml and fill it in.")
    with path.open("rb") as f:
        cfg = {**DEFAULTS, **tomllib.load(f)}
    topic = cfg["ntfy_topic"]
    if topic and (len(topic) < 20 or "REPLACE" in topic):
        raise SystemExit(
            "ntfy_topic is guessable. Generate one with:\n"
            "  python3 -c \"import secrets; print('iclicker-' + secrets.token_hex(16))\""
        )
    return cfg


class PollState:
    """Edge trigger: fire on closed->open, re-arm after CLOSE_TICKS closed reads in a row."""

    CLOSE_TICKS = 2

    def __init__(self):
        self.alerted = False
        self.closed_streak = 0

    def update(self, is_open: bool) -> bool:
        if is_open:
            self.closed_streak = 0
            if self.alerted:
                return False
            self.alerted = True
            return True
        self.closed_streak += 1
        if self.alerted and self.closed_streak >= self.CLOSE_TICKS:
            self.alerted = False
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Alert when an iClicker poll opens.")
    ap.add_argument("--record", action="store_true", help="save HTML + screenshot on every page change")
    ap.add_argument("--test-alert", action="store_true", help="fire all alerts once and exit")
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(args.config)

    if args.test_alert:
        results = fire_all(cfg)
        for name, ok in results.items():
            print(f"{name}: {'ok' if ok else 'FAILED'}")
        return 0 if all(results.values()) else 1

    raise SystemExit("watch mode not implemented yet")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all tests in `test_alerts.py`, `test_detect.py`, `test_watcher.py` pass (18 passed)

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher.py
git commit -m "feat: add config loading, poll state machine, --test-alert"
```

---

### Task 4: Browser loop + record mode

**Files:**
- Modify: `watcher.py`
- Create: `tests/fixtures/fake_class.html`
- Test: `tests/test_watcher.py` (append)

**Interfaces:**
- Consumes: `DETECT_JS`, `PollState`, `load_config`, `fire_all`.
- Produces:
  - `watcher.Recorder(out_dir: Path)` with `maybe_save(page, result: dict) -> bool` (True when a new snapshot was written).
  - `watcher.find_page(ctx, match: str) -> Page | None` — last page whose URL contains `match`.
  - `watcher.run_loop(ctx, cfg: dict, alert=fire_all, recorder: Recorder | None = None, max_ticks: int | None = None) -> None` — returns when `ctx` has zero pages, when ctx closes, or after `max_ticks`.
  - `watcher.watch(cfg: dict, record: bool = False) -> None` — launches persistent context and calls `run_loop`.
  - `watcher.PROFILE_DIR`, `watcher.RECORD_DIR`.

- [ ] **Step 1: Write fake class page**

`tests/fixtures/fake_class.html` — poll opens at 1.0s, closes at 2.5s, reopens at 4.0s:

```html
<!doctype html>
<html><body>
  <h1 id="status">Waiting for poll</h1>
  <div id="answers"></div>
  <script>
    const answers = document.getElementById("answers");
    const status = document.getElementById("status");
    function open() {
      status.textContent = "Poll open";
      answers.innerHTML = "<button>A</button><button>B</button><button>C</button><button>D</button>";
    }
    function close() {
      status.textContent = "Poll closed";
      answers.innerHTML = "";
    }
    setTimeout(open, 1000);
    setTimeout(close, 2500);
    setTimeout(open, 4000);
  </script>
</body></html>
```

- [ ] **Step 2: Write failing tests**

Append to `tests/test_watcher.py`:

```python
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from watcher import Recorder, find_page, run_loop

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


def test_find_page_ignores_other_pages(ctx):
    other = ctx.pages[0] if ctx.pages else ctx.new_page()
    other.goto((FIXTURES / "no_poll.html").as_uri())
    assert find_page(ctx, "fake_class.html") is None
    target = ctx.new_page()
    target.goto((FIXTURES / "fake_class.html").as_uri())
    assert find_page(ctx, "fake_class.html") is target


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'Recorder' from 'watcher'`

- [ ] **Step 4: Implement**

In `watcher.py`, update the imports block to:

```python
import argparse
import hashlib
import json
import logging
import sys
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from alerts import fire_all
```

Below `DETECT_JS`, add:

```python
PROFILE_DIR = Path.home() / ".iclicker-alert" / "profile"
RECORD_DIR = ROOT / "recordings"
```

Below `PollState`, add:

```python
class Recorder:
    """Saves page HTML + screenshot whenever the visible text changes."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.last_hash = None

    def maybe_save(self, page, result: dict) -> bool:
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest == self.last_hash:
            return False
        self.last_hash = digest
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (self.out_dir / f"{ts}.html").write_text(page.content())
        page.screenshot(path=str(self.out_dir / f"{ts}.png"), full_page=True)
        with (self.out_dir / "log.jsonl").open("a") as f:
            f.write(json.dumps({"ts": ts, "url": page.url, "detect": result}) + "\n")
        log.info("recorded %s (%s)", ts, result["reason"])
        return True


def find_page(ctx, match: str):
    pages = [p for p in ctx.pages if match in p.url]
    return pages[-1] if pages else None


def run_loop(ctx, cfg: dict, alert=fire_all, recorder: "Recorder | None" = None,
             max_ticks: int | None = None) -> None:
    closed = threading.Event()
    ctx.on("close", lambda _: closed.set())
    state = PollState()
    warned_missing = False
    ticks = 0
    while not closed.is_set() and (max_ticks is None or ticks < max_ticks):
        ticks += 1
        if not ctx.pages:
            log.info("browser window closed, exiting")
            return
        page = find_page(ctx, cfg["match"])
        if page is None:
            if not warned_missing:
                log.info("no page matching %r open; join class in the browser window", cfg["match"])
                warned_missing = True
        else:
            warned_missing = False
            try:
                result = page.evaluate(DETECT_JS)
                if recorder:
                    recorder.maybe_save(page, result)
            except PlaywrightError as e:
                log.debug("detect failed (page navigating?): %s", e)
                result = None
            if result is not None and state.update(result["open"]):
                log.info("POLL OPEN (%s)", result["reason"])
                threading.Thread(target=alert, args=(cfg,), daemon=True).start()
        time.sleep(cfg["interval_s"])


def watch(cfg: dict, record: bool = False) -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            channel=cfg["channel"] or None,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(cfg["url"])
            log.info("watching; log in and join class in the browser window (Ctrl-C to stop)")
            run_loop(ctx, cfg, recorder=Recorder(RECORD_DIR) if record else None)
        finally:
            try:
                ctx.close()
            except PlaywrightError:
                pass
```

In `main()`, replace `raise SystemExit("watch mode not implemented yet")` with:

```python
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        watch(cfg, record=args.record)
    except KeyboardInterrupt:
        log.info("stopped")
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: 22 passed

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher.py tests/fixtures/fake_class.html
git commit -m "feat: add browser watch loop and record mode"
```

---

### Task 5: README + manual verification

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: CLI from Tasks 3–4.
- Produces: setup + usage docs.

- [ ] **Step 1: Write `README.md`**

````markdown
# iclicker-alert

Pings your phone, Mac, and iMessage the moment an iClicker poll opens.
Only watches; you answer every poll yourself.

## Setup (once)

```bash
cd ~/iclicker-alert
uv sync
uv run playwright install chromium
cp config.example.toml config.toml
python3 -c "import secrets; print('iclicker-' + secrets.token_hex(16))"   # paste into ntfy_topic
```

1. Install the **ntfy** app on your phone, subscribe to your topic (server: ntfy.sh).
2. Set `imessage_to` in `config.toml` to your phone number or Apple ID email.
3. `uv run watcher.py --test-alert` — allow Terminal to control Messages when macOS asks.
   All three channels should print `ok` and arrive.

## In class

```bash
uv run watcher.py            # normal
uv run watcher.py --record   # first few classes: also saves page snapshots to recordings/
```

Log in and join your class in the Chromium window it opens. Login is remembered.
Leave the window open (can be behind other windows). Ctrl-C or close the window to stop.

If school/Google login refuses the browser, set `channel = "chrome"` in `config.toml`.

## Improving detection

After a `--record` class, `recordings/log.jsonl` shows what the detector saw on each
page change. Share a snapshot taken during a live poll to replace the heuristic in
`detect.js` with an exact rule.
````

- [ ] **Step 2: Manual check — test alerts**

Requires `config.toml` filled in by Max (topic + phone number).
Run: `uv run watcher.py --test-alert`
Expected: `ntfy: ok`, `mac: ok`, `imessage: ok`; push on phone, Mac banner, iMessage received.

- [ ] **Step 3: Manual check — watch against fake page**

Run: `uv run python -c "import watcher, pathlib; cfg = watcher.load_config(watcher.ROOT/'config.toml'); cfg.update(url=(watcher.ROOT/'tests/fixtures/fake_class.html').as_uri(), match='fake_class.html'); watcher.watch(cfg)"`
Expected: Chromium window opens fake page; within ~5s two `POLL OPEN` log lines and two sets of real alerts. Close the window → process exits with `browser window closed, exiting`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage"
```
