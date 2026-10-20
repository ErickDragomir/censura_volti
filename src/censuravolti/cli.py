"""Interfaccia a riga di comando. Senza argomenti avvia la GUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import AUDIO_MODES, Options, ProcessingError, default_output_path, process_video
from .ffmpeg_utils import FFmpegError
from .models import ModelError

WARNING = (
    "Attenzione: controlla manualmente il video finale, il rilevatore può perdere volti; "
    "la trasformazione della voce non garantisce l'anonimato (usa --audio mute)."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="censuravolti",
        description="Censura automaticamente i volti in un video (elaborazione locale). "
        "Senza argomenti avvia l'interfaccia grafica.",
    )
    parser.add_argument("input", help="video da censurare")
    parser.add_argument(
        "-o", "--output", help="file di destinazione (default: <nome>_censurato.mp4)"
    )
    parser.add_argument(
        "--audio",
        choices=AUDIO_MODES,
        default="anon",
        help="mute = rimuove l'audio (più sicuro); anon = trasforma la voce (default)",
    )
    parser.add_argument(
        "--keep-metadata",
        action="store_true",
        help="conserva metadati e capitoli originali (di default vengono rimossi)",
    )
    parser.add_argument("--model", help="percorso di un modello .tflite personalizzato")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="sovrascrive la destinazione senza chiedere"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        try:
            from .gui import main as gui_main
        except ImportError as exc:
            print(
                f"Interfaccia grafica non disponibile ({exc}).\n"
                "Su Linux installa tkinter (es. sudo apt install python3-tk) "
                "oppure usa la riga di comando: censuravolti --help",
                file=sys.stderr,
            )
            return 1
        gui_main()
        return 0

    args = build_parser().parse_args(argv)
    target = args.output or default_output_path(args.input)

    if Path(target).exists() and not args.yes:
        if not sys.stdin.isatty():
            print(f"Il file {target} esiste già: usa --yes per sovrascriverlo.", file=sys.stderr)
            return 2
        answer = input(f"Il file {target} esiste già. Sostituirlo? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sì", "y"):
            return 2

    options = Options(
        source=args.input,
        target=target,
        audio_mode=args.audio,
        strip_metadata=not args.keep_metadata,
        model_path=args.model,
    )
    try:
        result = process_video(options, log=print)
    except KeyboardInterrupt:
        print("Interrotto.", file=sys.stderr)
        return 130
    except (ProcessingError, FFmpegError, ModelError) as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 1

    print(f"\nFotogrammi elaborati: {result.frames} - rilevamenti: {result.detections}")
    print(WARNING)
    return 0
