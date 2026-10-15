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
