# SoundFonts

Drop a General-MIDI `.sf2` SoundFont in this directory and `--renderer fluidsynth`
will pick it up automatically (discovery order: `GeneralUser-GS.sf2` →
`FluidR3_GM.sf2` → any other `*.sf2`, alphabetically).

The files are **not committed** (30+ MB each) — download once:

```powershell
curl.exe -L -o "soundfonts\GeneralUser-GS.sf2" "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2"
```

Expected file (verified 2026-10-08):

- Size: 32,319,396 bytes
- SHA-256: `9575028C7A1F589F5770FCCC8CFF2734566AF40CD26ED836944E9A5152688CFE`

Check after download:

```powershell
Get-FileHash "soundfonts\GeneralUser-GS.sf2" -Algorithm SHA256
```

Any other SoundFont works too — pass it explicitly if you keep it elsewhere:

```powershell
python -m ui.cli --renderer fluidsynth --soundfont "C:\path\to\your.sf2"
```

Requires the `fluidsynth` program on PATH — see the README's
"Audio rendering" section for setup.
