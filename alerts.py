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
