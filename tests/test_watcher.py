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
