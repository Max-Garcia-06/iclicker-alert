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
