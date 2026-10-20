import pytest

from censuravolti import ffmpeg_utils
from censuravolti.ffmpeg_utils import (
    build_final_command,
    install_hint,
    parse_frame_count,
    parse_frame_rate,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("25/1", 25.0), ("30000/1001", 30000 / 1001), ("0/0", 25.0), ("abc", 25.0),
     ("1000/1", 25.0), (None, 25.0), ("0/1", 25.0)],
)
def test_parse_frame_rate(text, expected):
    assert parse_frame_rate(text) == pytest.approx(expected)


@pytest.mark.parametrize(("value", "expected"), [("120", 120), ("N/A", 0), (None, 0), (7, 7)])
def test_parse_frame_count(value, expected):
    assert parse_frame_count(value) == expected


def test_final_command_mute_has_no_audio():
    cmd = build_final_command("v.mp4", "src.mkv", "out.mp4", "mute", True, 10.0)
    assert "-an" in cmd
    assert "-af" not in cmd
    assert cmd[-1] == "out.mp4"


def test_final_command_anon_maps_source_audio():
    cmd = build_final_command("v.mp4", "src.mkv", "out.mp4", "anon", True, 10.0)
    assert "-af" in cmd
    assert "1:a:0?" in cmd
    assert "-an" not in cmd


def test_final_command_metadata_handling():
    stripped = build_final_command("v.mp4", "s.mkv", "o.mp4", "mute", True, 1.0)
    assert stripped[stripped.index("-map_metadata") + 1] == "-1"
    kept = build_final_command("v.mp4", "s.mkv", "o.mp4", "mute", False, 1.0)
    assert kept[kept.index("-map_metadata") + 1] == "1"


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_install_hint_per_platform(monkeypatch, platform):
    monkeypatch.setattr(ffmpeg_utils.sys, "platform", platform)
    hint = install_hint()
    assert "ffmpeg" in hint.lower()
    assert ("brew" in hint) == (platform == "darwin")
    assert ("winget" in hint) == (platform == "win32")
