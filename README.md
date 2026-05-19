# TI-99/4A Pixel Art (Krita plugin)

A Krita docker titled **"TI99/4A pixel art"** that turns the current
canvas — or just the active selection — into a TI Extended BASIC
program. The program uses `CALL CHAR` to redefine character cells and
`CALL HCHAR` to place them on the 32 x 24 TI screen, reproducing the
picture as pixel art on a real or emulated TI-99/4A.

## Requirements

* Krita 5.x (the plugin uses the `krita` Python module exposed inside
  the host process).
* Python 3.10+ on PATH if you want to run `build.bat` to produce an
  installable zip yourself. The plugin code itself only uses the Python
  shipped inside Krita.

## Install (pre-built zip)

1. Build the zip (see below) or download `ti99-pixel-art-plugin-<ver>.zip`
   from the project root.
2. In Krita open
   **Settings → Manage Resources → Open Resource Folder**, then go into
   the `pykrita\` subfolder. On Windows that is usually
   `%APPDATA%\krita\pykrita\`.
3. Extract the zip directly into that folder, so you end up with:

   ```
   pykrita\
     ti99_pixel_art.desktop
     ti99_pixel_art\
       __init__.py
       extension.py
       widget.py
       converter.py
       manual.html        (rendered from this README during build)
       LICENSE
   ```

4. Restart Krita.
5. Enable the plugin in **Settings → Configure Krita → Python Plugin
   Manager** (check the "TI-99/4A Pixel Art" box, then restart Krita
   again when prompted).
6. Show the docker via **Settings → Dockers → TI99/4A pixel art**.

## Use

1. Open an RGBA / 8-bit image in Krita.
2. (Optional) make a rectangular or freeform selection. Only the
   selection's bounding box will be converted.
3. In the docker, configure:
   * **Dot columns**, **Dot rows** — how many TI dots wide / tall the
     output should be. Rounded down to a multiple of 8 and clamped to
     `256 x 192` dots (= the full TI screen of `32 x 24` 8x8 char cells).
   * **Threshold** — 1..254 luminance cutoff. Lower keeps fewer pixels
     as ink.
   * **Char code start / end** — the range of TI character codes the
     plugin may redefine. Code 32 is reserved as the space character
     used by `CALL CLEAR`, so the lowest legal start is `33`. The
     unique-pattern budget is `end - start + 1`.
4. Click **1. Pixelate**. The plugin divides the source rect into
   `Dot columns x Dot rows` cells of natural size
   `(src_width / dot_cols) x (src_height / dot_rows)` source pixels.
   Each cell takes the **average luminance** of all the source pixels
   falling inside it and is set to black or white using the Threshold —
   no resampling, no resizing. The result is painted onto a new layer
   at the source rect's exact pixel dimensions.
5. Click **2. Generate code**. The Extended BASIC program appears in
   the read-only text area below. Unique 8x8 patterns are deduplicated
   (so a 4x4-cell picture can never produce more than 16 `CALL CHAR`
   lines). When the unique-pattern count exceeds the configured code
   range, extras snap to their nearest existing pattern by Hamming
   distance and the status line reports how many cells snapped.
6. Click **Copy code to clipboard**, paste into your TI emulator (or
   transfer to a real TI), `RUN`, and the picture appears.

Whenever you change Dot columns / Dot rows / Threshold, the cached
pixelation is invalidated and **Generate code** locks until you click
**Pixelate** again — step 2 can never silently run against stale bits.

## How the BASIC output is structured

```
100 CALL CLEAR
110 CALL SCREEN(15)
120 CALL CHAR(33,"<16-hex-digits>")   <- one line per unique 8x8 pattern
...
NNN CALL HCHAR(row, col, code [, count])   <- one line per run of cells
...
GOTO 9999
9999 GOTO 9999
```

* Each TI character is `8x8` pixels. One row = one byte, MSB = leftmost
  pixel. `CALL CHAR(code, "16-hex-digits")` redefines that cell.
* The picture is centred on the 32x24 TI screen.
* All-zero cells are skipped (CALL CLEAR has already filled the screen
  with space).
* Runs of identical codes on the same row collapse to a single
  `CALL HCHAR(row, col, code, count)`.

## Build (produce an installable zip)

From a Windows shell in the project root:

```cmd
build.bat
```

That calls `python .\scripts\package.py`, which:

1. Reads `__version__` from `ti99_pixel_art\__init__.py`.
2. Stages `ti99_pixel_art.desktop` + the `ti99_pixel_art\` package into
   `scripts\.package\`, stripping `__pycache__`, `*.pyc`, `*.pyo`, and
   dot-files.
3. Copies `LICENSE` and renders `README.md` into `manual.html` (using
   `markdown` if available, otherwise drops in `manual.md` as a
   fallback).
4. Zips the staged tree into
   `ti99-pixel-art-plugin-<version>.zip` at the project root.
5. Cleans the staging dir.

Run the converter unit tests directly with Python (no Krita needed) —
`ti99_pixel_art\converter.py` is fully importable outside the host:

```cmd
python -c "from ti99_pixel_art.converter import pixelate, bits_to_basic; print('ok')"
```

The widget / extension modules only import inside Krita because they
pull in the `krita` module that the host injects.

## Project layout

```
ti99-pixel-art-plugin\
  build.bat                  one-liner that calls scripts\package.py
  scripts\
    package.py               builder — produces the installable zip
  ti99_pixel_art.desktop     Krita service entry (X-KDE-Library = ti99_pixel_art)
  ti99_pixel_art\
    __init__.py              version + krita-gated extension import
    extension.py             registers Extension + DockWidgetFactory
    widget.py                'TI99/4A pixel art' dock UI
    converter.py             pure-Python pixelate + bits-to-BASIC
  README.md
  LICENSE
```

## License

MIT — see `LICENSE`.
