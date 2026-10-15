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
