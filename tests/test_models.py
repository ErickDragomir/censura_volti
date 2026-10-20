import pytest

from censuravolti import models
from censuravolti.models import ModelError, is_valid_model, resolve_model, user_data_dir


def make_model(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x1c\x00\x00\x00TFL3" + b"\x00" * 2048)
    return path


def test_is_valid_model(tmp_path):
    assert is_valid_model(make_model(tmp_path / "ok.tflite"))
    bad = tmp_path / "bad.tflite"
    bad.write_bytes(b"not a model" * 500)
    assert not is_valid_model(bad)
    assert not is_valid_model(tmp_path / "missing.tflite")


def test_resolve_explicit_path(tmp_path):
    model = make_model(tmp_path / "m.tflite")
    assert resolve_model(str(model)) == model


def test_resolve_explicit_invalid_raises(tmp_path):
    with pytest.raises(ModelError):
        resolve_model(str(tmp_path / "missing.tflite"))


def test_resolve_env_variable(tmp_path, monkeypatch):
    model = make_model(tmp_path / "env.tflite")
    monkeypatch.setenv(models.ENV_MODEL, str(model))
    assert resolve_model() == model


def test_resolve_uses_cached_model_without_download(tmp_path, monkeypatch):
    monkeypatch.delenv(models.ENV_MODEL, raising=False)
    monkeypatch.setattr(models.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    cached = make_model(tmp_path / "censuravolti" / models.MODEL_FILENAME)

    def fail(*args, **kwargs):
        raise AssertionError("non deve scaricare")

    monkeypatch.setattr(models, "download_model", fail)
    assert resolve_model() == cached


@pytest.mark.parametrize(
    ("platform", "env"),
    [("linux", "XDG_DATA_HOME"), ("win32", "LOCALAPPDATA")],
)
def test_user_data_dir_respects_environment(tmp_path, monkeypatch, platform, env):
    monkeypatch.setattr(models.sys, "platform", platform)
    monkeypatch.setenv(env, str(tmp_path))
    assert user_data_dir() == tmp_path / "censuravolti"
