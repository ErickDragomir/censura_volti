"""Utilita per FFmpeg/FFprobe: rilevamento, esecuzione e probe, uguali su ogni sistema."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from fractions import Fraction

AUDIO_FILTER = (
    "asetrate=44100*0.82,"
    "aresample=44100,"
    "atempo=1.2195,"
    "highpass=f=180,"
    "lowpass=f=3400,"
    "acompressor=threshold=-18dB:ratio=3:attack=5:release=80"
)


class FFmpegError(RuntimeError):
    """Errore di FFmpeg/FFprobe (assenti o comando fallito)."""


def _popen_kwargs() -> dict:
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        # Evita il lampeggio di finestre console quando l'app e' avviata dalla GUI.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def install_hint() -> str:
    """Come installare FFmpeg sul sistema corrente."""
    if sys.platform == "darwin":
        return "Installa FFmpeg con: brew install ffmpeg"
    if sys.platform == "win32":
        return "Installa FFmpeg con: winget install Gyan.FFmpeg (oppure: choco install ffmpeg)"
    return (
        "Installa FFmpeg con il gestore pacchetti della tua distribuzione, ad esempio:\n"
        "  Debian/Ubuntu: sudo apt install ffmpeg\n"
        "  Fedora (RPM Fusion): sudo dnf install ffmpeg\n"
        "  Arch: sudo pacman -S ffmpeg"
    )


def ensure_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegError(f"{' e '.join(missing)} non trovato nel PATH.\n{install_hint()}")


def run_command(args: list[str], description: str) -> str:
    """Esegue un comando; in caso di errore solleva FFmpegError con i dettagli."""
    result = subprocess.run(args, **_popen_kwargs())
    if result.returncode != 0:
        detail = result.stderr[-4000:] if result.stderr else "Errore sconosciuto."
        raise FFmpegError(f"{description}:\n{detail}")
    return result.stdout


def parse_frame_rate(text, default: float = 25.0, max_fps: float = 240.0) -> float:
    """Converte '30000/1001' (o '25') in fps; valori assurdi o illeggibili -> default."""
    try:
        fps = float(Fraction(str(text)))
    except (ValueError, ZeroDivisionError, TypeError):
        return default
    if not 0 < fps <= max_fps:
        return default
    return fps


def parse_frame_count(value) -> int:
    """Converte il conteggio fotogrammi di ffprobe; 'N/A' o assente -> 0."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def probe_video(path: str, count_frames: bool = False) -> dict:
    entries = "stream=width,height,avg_frame_rate,r_frame_rate,duration,nb_frames"
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
        entries += ",nb_read_frames"
    command += ["-select_streams", "v:0", "-show_entries", entries, "-of", "json", str(path)]

    output = run_command(command, "FFprobe non riesce a leggere le proprietà del video")
    streams = json.loads(output).get("streams", [])
    if not streams:
        raise FFmpegError("Nel file non è presente una traccia video.")
    return streams[0]


def build_normalize_command(source: str, dest: str, fps: float) -> list[str]:
    """Rende il flusso a frame rate costante, per una lettura affidabile con OpenCV."""
    return [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(source),
        "-map", "0:v:0",
        "-an", "-sn", "-dn",
        "-vf", f"fps={fps:.8f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dest),
    ]


def build_final_command(
    censored_video: str,
    source: str,
    target: str,
    audio_mode: str,
    strip_metadata: bool,
    duration: float,
) -> list[str]:
    """Unisce video censurato e audio originale (muto o trasformato).

    La sorgente e' sempre il secondo input: serve per l'audio e, se richiesto,
    per copiare metadati e capitoli originali.
    """
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(censored_video),
        "-i", str(source),
        "-map", "0:v:0",
    ]
    if audio_mode == "mute":
        cmd += ["-c:v", "copy", "-an"]
    else:
        cmd += [
            "-map", "1:a:0?",
            "-c:v", "copy",
            "-af", AUDIO_FILTER,
            "-c:a", "aac",
            "-b:a", "160k",
        ]

    # Limita l'output alla durata video reale, senza -shortest:
    # un flusso audio più breve non tronca il video.
    cmd += ["-t", f"{duration:.6f}", "-sn", "-dn"]

    if strip_metadata:
        cmd += [
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-metadata", "comment=", "-metadata", "title=",
        ]
    else:
        cmd += ["-map_metadata", "1", "-map_chapters", "1"]

    cmd.append(str(target))
    return cmd
