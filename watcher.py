"""Watch an iClicker tab and alert when a poll opens."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DETECT_JS = (ROOT / "detect.js").read_text()
