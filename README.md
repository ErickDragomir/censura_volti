# CensuraVolti

Censura automaticamente i volti in un video, con gestione di audio e metadati.
Tutto avviene **in locale** (OpenCV, MediaPipe, FFmpeg): nessun video viene caricato online.
Funziona su **Linux, macOS e Windows**, con interfaccia grafica o da riga di comando.

> **Attenzione:** nessun rilevatore trova tutti i volti in ogni fotogramma (volti piccoli,
> coperti o di profilo possono sfuggire) e la trasformazione della voce **non** garantisce
> l'anonimato vocale. Controlla sempre il video finale; per la massima protezione rimuovi l'audio.

## Requisiti

- Python 3.10 o superiore
- [FFmpeg](https://ffmpeg.org/) (inclusi `ffmpeg` e `ffprobe`) disponibile nel `PATH`
- Per la GUI: tkinter (incluso in Python su Windows e macOS)

| Sistema | Installare FFmpeg | tkinter |
|---|---|---|
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` | `sudo apt install python3-tk` |
| Linux (Arch) | `sudo pacman -S ffmpeg` | `sudo pacman -S tk` |
| macOS | `brew install ffmpeg` | `brew install python-tk` (solo con Python di Homebrew) |
| Windows | `winget install Gyan.FFmpeg` | incluso |

## Installazione

```bash
git clone <url-del-tuo-repository>
cd censuravolti
python -m venv .venv
# Linux/macOS: source .venv/bin/activate     Windows: .venv\Scripts\activate
pip install .
```

Per sviluppare: `pip install -e ".[dev]"`.

## Uso

**Interfaccia grafica** (senza argomenti):

```bash
censuravolti          # oppure: censuravolti-gui   /   python -m censuravolti
```

**Riga di comando:**

```bash
censuravolti video.mp4                       # crea video_censurato.mp4
censuravolti video.mp4 -o out.mp4 --audio mute
censuravolti video.mp4 --keep-metadata -y
censuravolti --help
```

| Opzione | Effetto |
|---|---|
| `--audio mute` | rimuove completamente l'audio (più sicuro) |
| `--audio anon` | trasforma la voce e conserva l'audio (default) |
| `--keep-metadata` | conserva metadati e capitoli (di default vengono rimossi) |
| `--model PERCORSO` | usa un modello `.tflite` personalizzato |
| `-y`, `--yes` | sovrascrive la destinazione senza chiedere |

## Modello di rilevamento

Al primo avvio il modello MediaPipe (BlazeFace) viene scaricato una sola volta in una cartella
per-utente (`~/.local/share/censuravolti`, `~/Library/Application Support/censuravolti`,
`%LOCALAPPDATA%\censuravolti`). Se sei offline, scaricalo a mano dall'URL indicato nell'errore
e salvalo come `face_detector.tflite` in quella cartella, oppure usa `--model` o la variabile
d'ambiente `CENSURAVOLTI_MODEL`.

## Sviluppo

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

La CI (GitHub Actions) esegue lint e test su Linux, macOS e Windows.

Struttura:

```
src/censuravolti/
  core.py          elaborazione (indipendente dall'interfaccia)
  ffmpeg_utils.py  comandi e probe FFmpeg
  models.py        percorso e download del modello
  cli.py / gui.py  interfacce
tests/
```

## Risoluzione problemi

- **«ffmpeg non trovato»**: installalo (vedi tabella) e riapri il terminale.
- **Percorsi con caratteri non ASCII su Windows**: se OpenCV non apre il video, prova una
  cartella di destinazione con percorso semplice.
- **Interfaccia grafica non disponibile su Linux**: installa tkinter o usa la riga di comando.

## Licenza

MIT, vedi [LICENSE](LICENSE).
