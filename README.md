# TI-99/4A Pixel Art (Krita plugin)

A Krita docker titled **"TI99/4A pixel art"** that turns the current
canvas into a TI Extended BASIC program. The program uses
`CALL CHAR` to redefine character cells and `CALL HCHAR` to place
them on the 32 x 24 TI screen, reproducing the picture as pixel art.

## Install

Copy these two items into your Krita `pykrita` directory:

```
pykrita/
  ti99_pixel_art.desktop
  ti99_pixel_art/
```

On Windows that directory is usually
`%APPDATA%\krita\pykrita\`.

Restart Krita, then enable the plugin under
**Settings → Configure Krita → Python Plugin Manager**.
Show the docker via **Settings → Dockers → TI99/4A pixel art**.

## Use

1. Open an image in Krita (RGBA / 8-bit).
2. In the **TI99/4A pixel art** docker, set **Dot columns** and
   **Dot rows**. They are rounded down to a multiple of 8 and
   clamped to the TI screen (256 x 192 dots = 32 x 24 cells).
3. Adjust the **Threshold** slider until the preview-by-eye is
   what you want. Lower values keep more dark pixels.
4. Click **Generate**. The Extended BASIC source appears below.
5. **Copy to clipboard**, paste into your TI emulator
   (or transfer to a real TI), `RUN`, and the picture appears.

## How it works

* Each TI character is `8x8` pixels. One row = one byte
  (MSB = leftmost pixel). `CALL CHAR(code, "16-hex-digits")`
  redefines a cell.
* The plugin resamples the image to the requested dot grid,
  thresholds each pixel to 1 bit by luminance, then packs every
  `8x8` block into a 16-hex-digit pattern.
* Identical patterns share a single `CALL CHAR` definition.
  Character codes 33..152 are used (120 unique cells). If the
  picture contains more, extras snap to their nearest neighbour
  by Hamming distance on the 64 pattern bits.
* All-zero (background) cells are mapped to code 32 (space) and
  do not consume a slot; `CALL CLEAR` at the start of the program
  fills the screen with spaces, so runs of background are emitted
  as nothing.
* Runs of identical codes on one row collapse to a single
  `CALL HCHAR(row, col, code, count)` call.
