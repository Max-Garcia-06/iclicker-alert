# iClicker Poll Alert — Design

Date: 2026-10-13

## Purpose

Alert Max the moment an iClicker poll opens during class so no poll is missed.
Max reads and answers every poll manually. The tool never reads question content
for answering and never clicks or submits anything in iClicker.

## Agreed requirements (from Max)

- iClicker runs in a laptop browser (student.iclicker.com) on macOS.
- Alerts go to three channels: phone push (ntfy.sh), macOS notification, iMessage to self.
- Approach: Python + Playwright watcher (option A).

## Assumptions

- iClicker DOM structure while a poll is live is unknown; first version uses a
  heuristic and a record mode to capture real pages for a precise rule later.
- Max is fine using a dedicated Playwright-launched Chrome window for iClicker.

## Layout

```
~/iclicker-alert/
  pyproject.toml          uv project, dependency: playwright
  config.example.toml     template; config.toml is gitignored
  watcher.py              CLI entry, browser loop, detection
  alerts.py               ntfy(), mac_notify(), imessage(), fire_all()
  detect.js               JS run in page, returns {open: bool, reason: str}
  tests/
    fixtures/poll.html, no_poll.html
    test_detect.py        detect.js against fixtures via Playwright
    test_alerts.py        alert functions with subprocess mocked
    test_watcher.py       config, state machine, recorder, loop e2e
  recordings/             gitignored, record-mode output
```

## Config (`config.toml`)

```toml
ntfy_topic = "iclicker-<32 random hex chars>"
imessage_to = "+1XXXXXXXXXX"   # phone number or Apple ID email
interval_s = 2.0
url = "https://student.iclicker.com/"
match = "iclicker.com"         # optional: substring of page URL to watch
channel = ""                   # optional: "chrome" to use installed Chrome if login is blocked
```

`ntfy_topic` shorter than 20 chars or containing `REPLACE` → exit with error
(short topics are guessable).

Missing `config.toml` → exit with message telling user to copy the example.
Empty `imessage_to` or `ntfy_topic` → that channel is skipped with a log line.

## Browser

`playwright.chromium.launch_persistent_context(user_data_dir="~/.iclicker-alert/profile", headless=False)`.
Login persists across runs. Opens `url` on start. Watches the most recently
opened page whose URL contains `match`. Zero pages left open → treated as
browser closed → exit.

## Detection

Every `interval_s`, evaluate `detect.js` in the page. Heuristic v1: poll is open
if ≥2 visible `button` / `[role=button]` elements have trimmed text exactly one
of `A`–`E`. Returns `{open, reason}`.

State machine: `closed → open` transition fires alerts once. Stays armed-off
until detection returns closed for 2 consecutive checks (avoids flicker
re-alerting), then re-arms.

## Record mode (`--record`)

Each tick, hash `document.body.innerText`. On change, write
`recordings/<timestamp>.html` (page content) and `<timestamp>.png`
(screenshot), plus append `{ts, url, detect_result}` to `recordings/log.jsonl`.
Detection and alerts still run in record mode.

## Alerts

- **ntfy:** `POST https://ntfy.sh/<topic>`, body `iClicker poll open`,
  headers `Priority: high`, `Title: iClicker`. Sent with `curl -m 5` (uses
  macOS system certs; avoids SSL cert issues in uv-managed Python).
- **macOS:** `osascript -e 'display notification "Poll open" with title "iClicker"'`.
- **iMessage:** `osascript` telling Messages to send `iClicker poll open` to
  `imessage_to` via the iMessage service. Recipient passed as an argv
  argument to the AppleScript, never interpolated into script text.

`fire_all()` runs all three concurrently (threads). Each wrapped in
try/except; failures logged, never raised. Returns per-channel success.

Message content is fixed text only: no question text, no course name.

## CLI

```
uv run watcher.py              # watch + alert
uv run watcher.py --record     # also capture page changes
uv run watcher.py --test-alert # fire all alerts once and exit
```

## Error handling

- Page navigates/reloads mid-evaluate → catch Playwright error, retry next tick.
- No iclicker page open → log once, keep waiting.
- Browser/context closed → exit 0 with message.
- Ctrl-C → close context, exit 0.

## Testing

- `test_detect.py`: load fixtures into headless Chromium, assert detect.js
  returns open for poll.html, closed for no_poll.html (including hidden A–E
  buttons → closed).
- `test_alerts.py`: mock `subprocess.run`; assert
  argv shape, that recipient is passed as argv not script text, and that one
  channel failing doesn't stop the others.
- Manual: `--test-alert` confirms all three arrive. First real class run in
  `--record` mode to validate/replace heuristic.

## Out of scope

Reading questions, choosing answers, clicking in iClicker, auto-joining class.
