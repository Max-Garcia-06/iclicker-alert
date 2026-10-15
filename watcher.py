"""Watch an iClicker tab and alert when a poll opens."""
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

ROOT = Path(__file__).resolve().parent
DETECT_JS = (ROOT / "detect.js").read_text()
PROFILE_DIR = Path.home() / ".iclicker-alert" / "profile"
RECORD_DIR = ROOT / "recordings"

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

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        watch(cfg, record=args.record)
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
