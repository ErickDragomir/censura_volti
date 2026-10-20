"""Gestione del modello MediaPipe: percorso per-utente e download automatico."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
MODEL_FILENAME = "face_detector.tflite"
ENV_MODEL = "CENSURAVOLTI_MODEL"


class ModelError(RuntimeError):
    """Modello assente, non valido o non scaricabile."""


def user_data_dir() -> Path:
    """Cartella dati per-utente (senza dipendenze esterne)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "censuravolti"


def is_valid_model(path: Path) -> bool:
    """Controllo minimo: i file TFLite hanno 'TFL3' ai byte 4-8."""
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return False
    return header[4:8] == b"TFL3"


def _manual_instructions() -> str:
    return (
        f"Scarica manualmente il modello da:\n{MODEL_URL}\n"
        f"e salvalo come {user_data_dir() / MODEL_FILENAME}, "
        f"oppure indicane il percorso con --model o con la variabile {ENV_MODEL}."
    )


def download_model(destination: Path, log=None) -> None:
    log = log or (lambda message: None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    log("Scarico il modello di rilevamento volti (una sola volta)…")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=30) as response, partial.open("wb") as out:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
        if not is_valid_model(partial):
            raise ModelError("Il file scaricato non è un modello TFLite valido.")
        os.replace(partial, destination)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelError(
            f"Download del modello non riuscito: {exc}\n{_manual_instructions()}"
        ) from exc
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
    log(f"Modello salvato in {destination}")


def resolve_model(explicit: str | os.PathLike | None = None, log=None) -> Path:
    """Ordine: argomento esplicito, variabile d'ambiente, cartella utente, download."""
    for label, value in (("--model", explicit), (ENV_MODEL, os.environ.get(ENV_MODEL))):
        if value:
            path = Path(value).expanduser()
            if not is_valid_model(path):
                raise ModelError(f"Modello non valido o non trovato ({label}): {path}")
            return path

    cached = user_data_dir() / MODEL_FILENAME
    if is_valid_model(cached):
        return cached
    download_model(cached, log)
    return cached
