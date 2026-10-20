"""Logica di elaborazione, indipendente dall'interfaccia (GUI o riga di comando).

Nota: la trasformazione della voce NON garantisce l'anonimato vocale.
Per una protezione piu forte, rimuovere completamente l'audio.
Controllare manualmente il video finale: nessun rilevatore garantisce di
individuare tutti i volti in ogni fotogramma.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_utils import (
    FFmpegError,
    build_final_command,
    build_normalize_command,
    ensure_ffmpeg,
    parse_frame_count,
    parse_frame_rate,
    probe_video,
    run_command,
)
from .models import resolve_model

AUDIO_MODES = ("mute", "anon")
PROGRESS_EVERY = 30


class ProcessingError(RuntimeError):
    """Errore di elaborazione con messaggio leggibile dall'utente."""


class CancelledError(Exception):
    """Elaborazione annullata dall'utente."""


@dataclass
class Options:
    source: str
    target: str
    audio_mode: str = "anon"
    strip_metadata: bool = True
    model_path: str | None = None


@dataclass
class Result:
    target: str
    frames: int
    detections: int


def default_output_path(source: str) -> str:
    path = Path(source)
    return str(path.with_name(path.stem + "_censurato.mp4"))


def padded_box(x: float, y: float, w: float, h: float, max_w: int, max_h: int):
    """Riquadro (x1, y1, x2, y2) del volto con margine, limitato al fotogramma.

    Restituisce None se il riquadro e' vuoto.
    """
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(max_w, int(x + w))
    y2 = min(max_h, int(y + h))
    if x2 <= x1 or y2 <= y1:
        return None

    pad_x = max(8, int((x2 - x1) * 0.30))
    pad_y = max(8, int((y2 - y1) * 0.35))
    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(max_w, x2 + pad_x),
        min(max_h, y2 + pad_y),
    )


def _noop_log(message: str) -> None:
    pass


def _noop_progress(percent, status) -> None:
    pass


def process_video(
    options: Options,
    log: Callable[[str], None] | None = None,
    progress: Callable[[float | None, str | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Result:
    """Censura i volti di un video. Il file di destinazione viene creato solo a lavoro finito."""
    log = log or _noop_log
    progress = progress or _noop_progress
    cancelled = cancelled or (lambda: False)

    source = Path(options.source)
    target = Path(options.target)

    if not source.is_file():
        raise ProcessingError("Il video sorgente non esiste.")
    if options.audio_mode not in AUDIO_MODES:
        raise ProcessingError(f"Modalità audio non valida: {options.audio_mode}")
    out_dir = target.resolve().parent
    if not out_dir.is_dir():
        raise ProcessingError(f"La cartella di destinazione non esiste: {out_dir}")
    if target.exists() and source.resolve() == target.resolve():
        raise ProcessingError("Il risultato deve essere un nuovo file.")

    ensure_ffmpeg()
    model_path = resolve_model(options.model_path, log)

    # Import pesanti solo qui: il resto del pacchetto resta importabile (e testabile) senza.
    import cv2
    import mediapipe as mp

    with tempfile.TemporaryDirectory(
        prefix=".censuravolti_", dir=out_dir, ignore_cleanup_errors=True
    ) as tmp:
        tmp_dir = Path(tmp)
        normalized_video = tmp_dir / "normalizzato.mp4"
        censored_video = tmp_dir / "censurato_video.mp4"
        final_video = tmp_dir / "finale.mp4"

        cap = None
        writer = None
        try:
            log("Controllo del video sorgente con FFprobe…")
            source_info = probe_video(str(source))
            width = int(source_info["width"])
            height = int(source_info["height"])
            rate_text = (
                source_info.get("avg_frame_rate") or source_info.get("r_frame_rate") or "25/1"
            )
            fps = parse_frame_rate(rate_text)

            progress(2, "Preparazione del video…")
            log(
                f"Sorgente: {width}x{height}, {fps:.3f} fps. "
                "Normalizzazione con FFmpeg in corso…"
            )
            run_command(
                build_normalize_command(str(source), str(normalized_video), fps),
                "Normalizzazione del video non riuscita",
            )
            log("Normalizzazione completata.")

            normalized_info = probe_video(str(normalized_video), count_frames=True)
            expected_frames = parse_frame_count(normalized_info.get("nb_read_frames"))
            norm_width = int(normalized_info["width"])
            norm_height = int(normalized_info["height"])
            norm_fps = parse_frame_rate(normalized_info.get("avg_frame_rate") or rate_text, fps)

            log(
                f"Video normalizzato: {norm_width}x{norm_height}, {norm_fps:.3f} fps, "
                f"{expected_frames or 'numero non disponibile'} fotogrammi attesi."
            )

            cap = cv2.VideoCapture(str(normalized_video))
            if not cap.isOpened():
                raise ProcessingError("OpenCV non riesce ad aprire il video normalizzato.")

            writer = cv2.VideoWriter(
                str(censored_video),
                cv2.VideoWriter_fourcc(*"mp4v"),
                norm_fps,
                (norm_width, norm_height),
            )
            if not writer.isOpened():
                raise ProcessingError("Non riesco a creare il video temporaneo censurato.")

            detector_options = mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                min_detection_confidence=0.5,
                min_suppression_threshold=0.3,
            )

            processed = 0
            total_detections = 0
            block_detections = 0
            log("Avvio rilevamento dei volti…")

            with mp.tasks.vision.FaceDetector.create_from_options(detector_options) as detector:
                while True:
                    if cancelled():
                        raise CancelledError()
                    ok, frame = cap.read()
                    if not ok:
                        break

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    timestamp_ms = int(processed * 1000 / norm_fps)
                    results = detector.detect_for_video(mp_image, timestamp_ms)

                    for detection in results.detections or []:
                        box = detection.bounding_box
                        area = padded_box(
                            box.origin_x, box.origin_y, box.width, box.height,
                            norm_width, norm_height,
                        )
                        if area is None:
                            continue
                        x1, y1, x2, y2 = area
                        frame[y1:y2, x1:x2] = 0
                        block_detections += 1
                        total_detections += 1

                    writer.write(frame)
                    processed += 1

                    if processed % PROGRESS_EVERY == 0:
                        pct = 5.0
                        if expected_frames:
                            pct = min(90.0, 5 + 85 * processed / expected_frames)
                        suffix = f"/{expected_frames}" if expected_frames else ""
                        progress(pct, f"Analisi volti: {processed}{suffix} fotogrammi")
                        log(
                            f"Elaborati {processed}{suffix} fotogrammi; "
                            f"rilevamenti nell'ultimo blocco: {block_detections}, "
                            f"totale: {total_detections}."
                        )
                        block_detections = 0

            cap.release()
            cap = None
            writer.release()
            writer = None

            if processed == 0:
                raise ProcessingError("Non è stato letto alcun fotogramma.")

            log(f"Lettura terminata: {processed} fotogrammi elaborati.")
            if expected_frames and processed != expected_frames:
                raise ProcessingError(
                    f"Elaborazione incompleta: OpenCV ha letto {processed} fotogrammi, "
                    f"ma FFprobe ne rileva {expected_frames} nel video normalizzato. "
                    "Il risultato non verrà dichiarato completo."
                )

            log("Verifica del video censurato temporaneo…")
            censored_info = probe_video(str(censored_video), count_frames=True)
            censored_count = parse_frame_count(censored_info.get("nb_read_frames"))
            if censored_count and censored_count != processed:
                raise ProcessingError(
                    f"Il video temporaneo contiene {censored_count} fotogrammi, "
                    f"ma ne erano stati elaborati {processed}. "
                    "Il risultato non verrà dichiarato completo."
                )

            duration = processed / norm_fps
            progress(93, "Unione audio/video e pulizia metadati…")
            log(f"Fotogrammi verificati. Durata video calcolata: {duration:.3f} secondi.")

            run_command(
                build_final_command(
                    str(censored_video), str(source), str(final_video),
                    options.audio_mode, options.strip_metadata, duration,
                ),
                "Creazione del file finale non riuscita",
            )

            if not final_video.is_file() or final_video.stat().st_size == 0:
                raise ProcessingError("FFmpeg non ha prodotto un file finale valido.")

            final_info = probe_video(str(final_video), count_frames=True)
            final_count = parse_frame_count(final_info.get("nb_read_frames"))
            if final_count and final_count < processed:
                raise ProcessingError(
                    f"Il file finale contiene {final_count} fotogrammi, "
                    f"ma ne erano stati elaborati {processed}. Il file finale è incompleto."
                )
            log(
                f"Verifica finale superata: {final_count or 'conteggio non disponibile'} "
                "fotogrammi nel file finale."
            )

            # Solo ora il risultato sostituisce (atomicamente) la destinazione:
            # un fallimento non cancella mai un file preesistente.
            os.replace(final_video, target)
            log(f"Completato. File salvato in: {target}")
            progress(100, "Completato.")
            return Result(str(target), processed, total_detections)

        except FFmpegError as exc:
            raise ProcessingError(str(exc)) from exc
        finally:
            if cap is not None:
                cap.release()
            if writer is not None:
                writer.release()
