"""Interfaccia grafica (tkinter)."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import CancelledError, Options, default_output_path, process_video
from .ffmpeg_utils import FFmpegError, ensure_ffmpeg

VIDEO_TYPES = [
    ("Video", "*.mp4 *.mkv *.avi *.mov *.webm *.m4v"),
    ("Tutti i file", "*.*"),
]

BG = "#1e1e1e"
PANEL = "#252525"
RED = "#cc0000"
RED_HOVER = "#e02020"
FG = "#eeeeee"
MUTED = "#bdbdbd"
ENTRY_BG = "#303030"

NOTE = (
    "La trasformazione audio non garantisce l'anonimato. "
    "Controlla manualmente tutto il filmato: volti piccoli, coperti "
    "o di profilo potrebbero non essere rilevati."
)


class FaceCensorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("CensuraVolti")
        self.root.geometry("900x680")
        self.root.minsize(720, 560)
        self.root.configure(bg=BG)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status = tk.StringVar(value="Seleziona un video per iniziare.")
        self.progress = tk.DoubleVar(value=0)
        self.audio_mode = tk.StringVar(value="anon")
        self.strip_metadata = tk.BooleanVar(value=True)

        # Il thread di lavoro non tocca mai i widget: posta funzioni in questa coda,
        # che viene svuotata dal thread principale (sicuro su Windows, macOS e Linux).
        self._events: queue.Queue = queue.Queue()
        self._cancel = threading.Event()

        self._configure_style()
        self._build_widgets()
        self.log("Applicazione avviata. I messaggi di elaborazione appariranno qui.")
        self.root.after(100, self._drain_events)

    # ---------- costruzione interfaccia ----------

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=16, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(11, weight=1)

        ttk.Label(outer, text="CENSURAVOLTI", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        ttk.Label(outer, text="Video da censurare:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(outer, textvariable=self.input_path, style="Dark.TEntry").grid(
            row=1, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(outer, text="Sfoglia…", command=self.choose_input, style="Red.TButton").grid(
            row=1, column=2, pady=5
        )

        ttk.Label(outer, text="Salva risultato in:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(outer, textvariable=self.output_path, style="Dark.TEntry").grid(
            row=2, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(outer, text="Scegli…", command=self.choose_output, style="Red.TButton").grid(
            row=2, column=2, pady=5
        )

        ttk.Separator(outer, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=10
        )

        ttk.Label(outer, text="Audio:", style="Section.TLabel").grid(
            row=4, column=0, sticky="nw", pady=3
        )
        audio_frame = ttk.Frame(outer, style="App.TFrame")
        audio_frame.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(
            audio_frame, text="Rimuovi completamente (più sicuro)",
            variable=self.audio_mode, value="mute", style="Dark.TRadiobutton",
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            audio_frame, text="Trasforma la voce e conserva l'audio",
            variable=self.audio_mode, value="anon", style="Dark.TRadiobutton",
        ).pack(anchor="w", pady=2)

        ttk.Checkbutton(
            outer, text="Rimuovi metadati e capitoli dal file finale",
            variable=self.strip_metadata, style="Dark.TCheckbutton",
        ).grid(row=5, column=1, columnspan=2, sticky="w", pady=(7, 4))

        self.note_label = ttk.Label(outer, text=NOTE, wraplength=850, style="Muted.TLabel")
        self.note_label.grid(row=6, column=0, columnspan=3, sticky="w", pady=(3, 9))

        buttons = ttk.Frame(outer, style="App.TFrame")
        buttons.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        buttons.columnconfigure(0, weight=1)
        self.start_button = ttk.Button(
            buttons, text="Avvia censura", command=self.start, style="Red.TButton"
        )
        self.start_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = ttk.Button(
            buttons, text="Annulla", command=self.cancel, style="Small.TButton", state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, padx=(8, 0))

        ttk.Progressbar(
            outer, variable=self.progress, maximum=100, style="Red.Horizontal.TProgressbar"
        ).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        self.status_label = ttk.Label(
            outer, textvariable=self.status, style="Status.TLabel", wraplength=850
        )
        self.status_label.grid(row=9, column=0, columnspan=3, sticky="new", pady=(0, 6))

        log_header = ttk.Frame(outer, style="App.TFrame")
        log_header.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(3, 4))
        ttk.Label(log_header, text="LOG ELABORAZIONE", style="Section.TLabel").pack(side="left")
        ttk.Button(
            log_header, text="Pulisci log", command=self.clear_log, style="Small.TButton"
        ).pack(side="right")

        log_frame = ttk.Frame(outer, style="App.TFrame")
        log_frame.grid(row=11, column=0, columnspan=3, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word", state="disabled",
            bg=BG, fg=FG, insertbackground=FG, selectbackground=RED,
            relief="flat", borderwidth=1, highlightthickness=1,
            highlightbackground="#444444", highlightcolor=RED,
            font="TkFixedFont",  # monospace corretto su ogni sistema
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Il testo a capo segue la larghezza della finestra.
        outer.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        wrap = max(300, event.width - 40)
        self.note_label.configure(wraplength=wrap)
        self.status_label.configure(wraplength=wrap)

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")  # unico tema che rispetta i colori su tutti i sistemi
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Title.TLabel", background=BG, foreground=RED,
                        font=("TkDefaultFont", 17, "bold"))
        style.configure("Section.TLabel", background=BG, foreground=FG,
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Status.TLabel", background=BG, foreground=FG,
                        font=("TkDefaultFont", 9))
        style.configure("Dark.TEntry", fieldbackground=ENTRY_BG, foreground=FG,
                        insertcolor=FG, bordercolor="#555555", lightcolor="#555555",
                        darkcolor="#333333")
        style.map("Dark.TEntry", fieldbackground=[("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Red.TButton", background=RED, foreground="#ffffff",
                        padding=(10, 6), borderwidth=0, focusthickness=1, focuscolor=RED)
        style.map("Red.TButton",
                  background=[("active", RED_HOVER), ("pressed", "#990000"),
                              ("disabled", "#555555")],
                  foreground=[("disabled", "#bbbbbb")])
        style.configure("Small.TButton", background=PANEL, foreground=FG,
                        padding=(7, 3), borderwidth=0)
        style.map("Small.TButton", background=[("active", "#3a3a3a")],
                  foreground=[("disabled", "#777777")])
        for name in ("Dark.TRadiobutton", "Dark.TCheckbutton"):
            style.configure(name, background=BG, foreground=FG)
            style.map(name, background=[("active", BG)], foreground=[("disabled", MUTED)])
        style.configure("Red.Horizontal.TProgressbar", troughcolor=PANEL, background=RED,
                        bordercolor=PANEL, lightcolor=RED, darkcolor=RED)
        style.configure("TSeparator", background="#444444")

    # ---------- comunicazione tra thread ----------

    def _post(self, func):
        self._events.put(func)

    def _drain_events(self):
        try:
            while True:
                self._events.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def log(self, message):
        """Sicuro da qualsiasi thread."""
        self._post(lambda: self._append_log(message))

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(message).rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def update_ui(self, progress=None, status=None):
        def apply():
            if progress is not None:
                self.progress.set(progress)
            if status is not None:
                self.status.set(status)
        self._post(apply)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- azioni ----------

    def choose_input(self):
        path = filedialog.askopenfilename(title="Scegli un video", filetypes=VIDEO_TYPES)
        if path:
            self.input_path.set(path)
            self.output_path.set(default_output_path(path))

    def choose_output(self):
        path = filedialog.asksaveasfilename(
            title="Salva il video censurato",
            defaultextension=".mp4",
            filetypes=[("Video MP4", "*.mp4")],
        )
        if path:
            self.output_path.set(path)

    def start(self):
        source = self.input_path.get().strip()
        target = self.output_path.get().strip()

        if not source or not Path(source).is_file():
            messagebox.showerror("Video mancante", "Seleziona un file video valido.")
            return
        if not target:
            messagebox.showerror("Destinazione mancante", "Scegli dove salvare il risultato.")
            return
        if Path(target).exists() and Path(source).resolve() == Path(target).resolve():
            messagebox.showerror("Percorso non valido", "Il risultato deve essere un nuovo file.")
            return
        if Path(target).exists() and not messagebox.askyesno(
            "Sovrascrivere il file?", "Il file di destinazione esiste già. Vuoi sostituirlo?"
        ):
            return
        try:
            ensure_ffmpeg()
        except FFmpegError as exc:
            messagebox.showerror("FFmpeg non trovato", str(exc))
            return

        options = Options(
            source=source,
            target=target,
            audio_mode=self.audio_mode.get(),
            strip_metadata=self.strip_metadata.get(),
        )

        self._cancel.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.set(0)
        self.status.set("Avvio elaborazione…")
        self.log("=" * 55)
        self.log(f"Sorgente: {source}")
        self.log(f"Destinazione: {target}")
        self.log(f"Audio: {'rimosso' if options.audio_mode == 'mute' else 'trasformato'}")
        self.log(f"Rimozione metadati: {'sì' if options.strip_metadata else 'no'}")

        threading.Thread(target=self._worker, args=(options,), daemon=True).start()

    def cancel(self):
        self._cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("Annullamento in corso…")

    def _worker(self, options: Options):
        try:
            result = process_video(
                options,
                log=self.log,
                progress=self.update_ui,
                cancelled=self._cancel.is_set,
            )
        except CancelledError:
            self.log("Elaborazione annullata.")
            self.update_ui(status="Elaborazione annullata.")
        except Exception as exc:  # noqa: BLE001 - qualsiasi errore va mostrato all'utente
            message = str(exc)
            self.log(f"ERRORE: {message}")
            self.update_ui(status="Elaborazione non riuscita.")
            self._post(lambda: messagebox.showerror("Errore", message))
        else:
            self._post(lambda: messagebox.showinfo(
                "Censura completata",
                f"Video salvato in:\n{result.target}\n\n"
                f"Fotogrammi elaborati: {result.frames}\n"
                f"Rilevamenti di volti: {result.detections}\n\n"
                "Controlla manualmente il filmato: il rilevatore può perdere "
                "volti e la trasformazione della voce non garantisce l'anonimato.",
            ))
        finally:
            self._post(self._finish)

    def _finish(self):
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")


def main():
    root = tk.Tk()
    FaceCensorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
