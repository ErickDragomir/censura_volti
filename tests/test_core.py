from pathlib import Path

import pytest

from censuravolti.core import (
    Options,
    ProcessingError,
    default_output_path,
    padded_box,
    process_video,
)


def test_default_output_path():
    result = Path(default_output_path(str(Path("a") / "clip.mov")))
    assert result == Path("a") / "clip_censurato.mp4"


def test_padded_box_adds_margin_and_clamps():
    x1, y1, x2, y2 = padded_box(100, 100, 100, 100, 1000, 1000)
    assert (x1, y1, x2, y2) == (70, 65, 230, 235)
    # vicino ai bordi resta dentro il fotogramma
    assert padded_box(0, 0, 50, 50, 60, 60) == (0, 0, 60, 60)


def test_padded_box_empty_is_none():
    assert padded_box(2000, 10, 50, 50, 100, 100) is None
    assert padded_box(10, 10, 0, 50, 100, 100) is None


def test_missing_source_is_reported(tmp_path):
    options = Options(source=str(tmp_path / "nope.mp4"), target=str(tmp_path / "out.mp4"))
    with pytest.raises(ProcessingError):
        process_video(options)


def test_invalid_audio_mode_is_reported(tmp_path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    options = Options(source=str(source), target=str(tmp_path / "out.mp4"), audio_mode="boh")
    with pytest.raises(ProcessingError):
        process_video(options)


def test_same_source_and_target_is_rejected(tmp_path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    with pytest.raises(ProcessingError):
        process_video(Options(source=str(source), target=str(source)))
