"""
Optional simple GUI (tkinter).

Launch with ``python main.py --gui``. Every option can be left on "auto" to let
the seed choose it; generation runs in a background thread so the window stays
responsive while the audio renders.
"""

from __future__ import annotations

import threading
from typing import Dict


def launch_gui() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as e:  # pragma: no cover - depends on the system
        raise ImportError("tkinter is not available (on Debian/Ubuntu: sudo apt install python3-tk)") from e

    from config.settings import BPM_MAX, BPM_MIN, COMMON_KEYS, DEFAULTS, SCALES, STYLE_LABELS, STYLES
    from core.generator import TranceGenerator

    root = tk.Tk()
    root.title("HighTrance – Goa & High-Tech Trance Generator")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=14)
    frame.grid()

    vars_: Dict[str, tk.Variable] = {
        "style": tk.StringVar(value=DEFAULTS["style"]),
        "bpm": tk.StringVar(value=str(DEFAULTS["bpm"])),
        "length": tk.StringVar(value=str(DEFAULTS["length"])),
        "key": tk.StringVar(value=DEFAULTS["key"]),
        "scale": tk.StringVar(value="auto"),
        "intensity": tk.DoubleVar(value=DEFAULTS["intensity"]),
        "seed": tk.StringVar(value=""),
        "output": tk.StringVar(value="output"),
        "audio": tk.BooleanVar(value=False),
        "format": tk.StringVar(value="wav"),
    }

    row = 0

    def add(label, widget):
        nonlocal row
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

    add("Style", ttk.Combobox(frame, textvariable=vars_["style"], values=list(STYLES), state="readonly"))
    ttk.Label(frame, text=" / ".join(STYLE_LABELS.values()), foreground="gray").grid(
        row=row, column=0, columnspan=2, sticky="w")
    row += 1
    add(f"BPM ({BPM_MIN}-{BPM_MAX} or auto)",
        ttk.Combobox(frame, textvariable=vars_["bpm"], values=["auto"] + list(range(BPM_MIN, BPM_MAX + 1))))
    add("Length (min or auto)", ttk.Combobox(frame, textvariable=vars_["length"],
                                             values=["auto", 6, 6.5, 7, 7.5, 8, 8.5, 9]))
    add("Key", ttk.Combobox(frame, textvariable=vars_["key"], values=["auto"] + COMMON_KEYS))
    add("Scale", ttk.Combobox(frame, textvariable=vars_["scale"], values=["auto"] + sorted(SCALES),
                              state="readonly"))
    add("Intensity", ttk.Scale(frame, from_=0.0, to=1.0, variable=vars_["intensity"], orient="horizontal"))
    add("Seed (empty = random)", ttk.Entry(frame, textvariable=vars_["seed"]))
    add("Output folder", ttk.Entry(frame, textvariable=vars_["output"]))
    add("Render audio", ttk.Checkbutton(frame, variable=vars_["audio"]))
    add("Audio format", ttk.Combobox(frame, textvariable=vars_["format"], values=["wav", "mp3"], state="readonly"))

    status = tk.StringVar(value="Ready.")
    progress = ttk.Progressbar(frame, mode="determinate", maximum=1.0, length=320)
    button = ttk.Button(frame, text="Generate track")
    button.grid(row=row, column=0, columnspan=2, pady=(10, 4), sticky="ew")
    progress.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
    ttk.Label(frame, textvariable=status, wraplength=380, justify="left").grid(
        row=row + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def opt(name):
        v = str(vars_[name].get()).strip()
        return None if v.lower() in ("", "auto") else v

    def on_progress(message, fraction):
        root.after(0, lambda: (status.set(message + "..."), progress.configure(value=fraction)))

    def worker():
        try:
            seed = opt("seed")
            gen = TranceGenerator(
                style=vars_["style"].get(), bpm=opt("bpm"), length_minutes=opt("length"), key=opt("key"),
                scale=opt("scale"), seed=int(seed) if seed else None,
                intensity=round(float(vars_["intensity"].get()), 2), output_dir=vars_["output"].get(),
                audio_format=vars_["format"].get(), verbose=False)
            on_progress("Composing", 0.05)
            result = gen.generate(render_audio=vars_["audio"].get(), progress=on_progress)
            text = (f"Done! seed={result['seed']}, {result['bpm']} BPM, {result['key']} "
                    f"({result['scale'].replace('_', ' ')})\nMIDI: {result['midi_path']}")
            if result["audio_path"]:
                text += f"\nAudio: {result['audio_path']}"
            for err in result["errors"]:
                text += f"\n! {err}"
            root.after(0, lambda: (status.set(text), progress.configure(value=1.0)))
        except Exception as e:  # show any problem to the user instead of crashing the GUI
            msg = str(e)
            root.after(0, lambda: (status.set("Error."), messagebox.showerror("Generation failed", msg)))
        finally:
            root.after(0, lambda: button.configure(state="normal"))

    def start():
        button.configure(state="disabled")
        progress.configure(value=0.0)
        status.set("Generating...")
        threading.Thread(target=worker, daemon=True).start()

    button.configure(command=start)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
