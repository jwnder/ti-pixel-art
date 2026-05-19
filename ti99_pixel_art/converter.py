"""Pure-Python conversion: Krita image bytes -> TI-99/4A CALL CHAR Extended BASIC code.

TI-99/4A character cell layout
------------------------------
* Each character is 8 rows tall and 8 bits (pixels) wide.
* One row = one byte. Bit 7 (0x80) is the LEFTMOST pixel.
* CALL CHAR takes the cell as 16 hex digits: 2 hex per row, 8 rows.
* CALL HCHAR(row, col, code [, count]) plots characters on the 32x24 screen
  (rows 1..24, cols 1..32).

Two-stage flow
--------------
1. ``pixelate(...)``  takes the raw Krita BGRA bytes, resamples to the dot
   grid and thresholds each pixel, returning a ``PixelatedImage`` (a bit
   matrix plus dot/character dimensions). The widget can paint this back
   onto a Krita layer so the user sees the 'squares' before committing.
2. ``bits_to_basic(...)`` takes that ``PixelatedImage`` plus the user's
   character-code range and produces ``ConversionResult.basic_program``.

The widget calls these two steps from separate buttons; everything except
``ValueError`` for bad input is deterministic and side-effect free.
"""

from __future__ import annotations

from dataclasses import dataclass

# Hard cap on the TI screen: 32x24 character cells = 256x192 dots.
TI_SCREEN_COLS = 32
TI_SCREEN_ROWS = 24
DOT_MAX_W = TI_SCREEN_COLS * 8
DOT_MAX_H = TI_SCREEN_ROWS * 8


@dataclass
class CharCell:
    """One redefined character: the 8 row-bytes and the assigned code."""

    code: int
    rows: tuple[int, int, int, int, int, int, int, int]

    @property
    def hex_pattern(self) -> str:
        return "".join(f"{b:02X}" for b in self.rows)


@dataclass
class PixelatedImage:
    """Result of step 1. The bit matrix is ``dot_rows`` rows of ``dot_cols``
    ints (0 = background, 1 = ink), and the picture decomposes cleanly into
    8x8 character cells of size ``char_cols`` x ``char_rows``.
    """

    dot_cols: int
    dot_rows: int
    char_cols: int
    char_rows: int
    bits: list[list[int]]


@dataclass
class ConversionResult:
    char_cols: int
    char_rows: int
    cells: list[CharCell]  # unique redefined characters
    layout: list[list[int]]  # layout[row][col] = TI character code
    basic_program: str
    skipped_patterns: int  # how many cells had to snap to a neighbour


# ---------------------------------------------------------------------------
# Step 1 — pixelate
# ---------------------------------------------------------------------------

def _resample_nearest(
    src: bytes, src_w: int, src_h: int, dst_w: int, dst_h: int, channels: int
) -> bytearray:
    """Nearest-neighbour resample of packed pixel bytes."""
    out = bytearray(dst_w * dst_h * channels)
    for y in range(dst_h):
        sy = (y * src_h) // dst_h
        if sy >= src_h:
            sy = src_h - 1
        src_row_off = sy * src_w * channels
        dst_row_off = y * dst_w * channels
        for x in range(dst_w):
            sx = (x * src_w) // dst_w
            if sx >= src_w:
                sx = src_w - 1
            s = src_row_off + sx * channels
            d = dst_row_off + x * channels
            out[d : d + channels] = src[s : s + channels]
    return out


def _luminance_bits(
    pixels: bytearray, width: int, height: int, channels: int, threshold: int
) -> list[list[int]]:
    """Return a height-by-width matrix of 0/1, with 1 meaning 'foreground (ink)'.

    Krita gives BGRA bytes (channels=4). Pixel is ink if its luminance is
    darker than the threshold, so dark strokes on a light canvas become set
    bits (the natural TI black-ink-on-light-background reading).
    """
    bits = [[0] * width for _ in range(height)]
    for y in range(height):
        row_off = y * width * channels
        row = bits[y]
        for x in range(width):
            p = row_off + x * channels
            if channels >= 3:
                b = pixels[p]
                g = pixels[p + 1]
                r = pixels[p + 2]
                a = pixels[p + 3] if channels >= 4 else 255
            else:
                r = g = b = pixels[p]
                a = 255
            if a < 16:
                lum = 255  # transparent reads as background
            else:
                lum = (299 * r + 587 * g + 114 * b) // 1000
            row[x] = 1 if lum < threshold else 0
    return bits


def pixelate(
    pixels: bytes,
    src_width: int,
    src_height: int,
    dot_cols: int,
    dot_rows: int,
    threshold: int = 128,
    channels: int = 4,
) -> PixelatedImage:
    """Step 1: turn the Krita image into a TI-resolution 1-bit matrix.

    ``dot_cols`` and ``dot_rows`` are the requested pixel dimensions of the
    interpolated image. They are rounded down to a multiple of 8 and clamped
    to the TI screen (256x192 dots) so the picture decomposes cleanly into
    8x8 character cells.
    """
    if dot_cols < 8 or dot_rows < 8:
        raise ValueError("dot columns and rows must be at least 8")
    dot_cols = min(DOT_MAX_W, (dot_cols // 8) * 8)
    dot_rows = min(DOT_MAX_H, (dot_rows // 8) * 8)
    if src_width <= 0 or src_height <= 0:
        raise ValueError("source image has zero size")
    if len(pixels) < src_width * src_height * channels:
        raise ValueError("pixel buffer is smaller than width*height*channels")

    resampled = _resample_nearest(
        pixels, src_width, src_height, dot_cols, dot_rows, channels
    )
    bits = _luminance_bits(resampled, dot_cols, dot_rows, channels, threshold)
    return PixelatedImage(
        dot_cols=dot_cols,
        dot_rows=dot_rows,
        char_cols=dot_cols // 8,
        char_rows=dot_rows // 8,
        bits=bits,
    )


def bits_to_bgra(
    pixel_img: PixelatedImage,
    out_width: int,
    out_height: int,
    ink_bgra: tuple[int, int, int, int] = (0, 0, 0, 255),
    bg_bgra: tuple[int, int, int, int] = (255, 255, 255, 255),
) -> bytes:
    """Render the pixelated bit matrix into BGRA bytes at ``out_width`` x
    ``out_height``, scaling each dot up to a (out_w / dot_cols, out_h /
    dot_rows) coloured square. Used to paint the 'squares' preview onto a
    Krita layer matching the canvas size.
    """
    if out_width <= 0 or out_height <= 0:
        raise ValueError("output size must be positive")
    bits = pixel_img.bits
    dc = pixel_img.dot_cols
    dr = pixel_img.dot_rows

    ink = bytes(ink_bgra)
    bg = bytes(bg_bgra)
    out = bytearray(out_width * out_height * 4)

    # Precompute the dot index for each output x; the row computation we do
    # inline because rows write contiguous spans.
    x_lut = [min(dc - 1, (x * dc) // out_width) for x in range(out_width)]

    for y in range(out_height):
        sy = min(dr - 1, (y * dr) // out_height)
        row = bits[sy]
        off = y * out_width * 4
        for x in range(out_width):
            colour = ink if row[x_lut[x]] else bg
            out[off : off + 4] = colour
            off += 4
    return bytes(out)


# ---------------------------------------------------------------------------
# Step 2 — bits to BASIC
# ---------------------------------------------------------------------------

def _pattern_for_cell(bits: list[list[int]], cx: int, cy: int) -> tuple[int, ...]:
    """Pack the 8x8 block at character position (cx, cy) into 8 row-bytes."""
    rows: list[int] = []
    base_x = cx * 8
    base_y = cy * 8
    for r in range(8):
        row = bits[base_y + r]
        byte = 0
        for c in range(8):
            if row[base_x + c]:
                byte |= 1 << (7 - c)
        rows.append(byte)
    return tuple(rows)


def _hamming(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    s = 0
    for i in range(8):
        s += bin(a[i] ^ b[i]).count("1")
    return s


def _assign_codes(
    char_cols: int,
    char_rows: int,
    bits: list[list[int]],
    code_start: int,
    code_end: int,
) -> tuple[list[CharCell], list[list[int]], int]:
    """Build the unique character table and the layout grid for codes in
    ``[code_start..code_end]``. All-zero cells map to code 32 (space) and
    do not consume a slot. Returns ``(cells, layout, snapped)`` where
    ``snapped`` counts cells that had to merge onto a neighbour because the
    code range was exhausted.
    """
    pattern_to_code: dict[tuple[int, ...], int] = {}
    cells: list[CharCell] = []
    layout: list[list[int]] = []
    next_code = code_start
    snapped = 0

    for cy in range(char_rows):
        row_layout: list[int] = []
        for cx in range(char_cols):
            pat = _pattern_for_cell(bits, cx, cy)
            if all(b == 0 for b in pat):
                row_layout.append(32)
                continue
            code = pattern_to_code.get(pat)
            if code is None:
                if next_code <= code_end:
                    code = next_code
                    next_code += 1
                    pattern_to_code[pat] = code
                    cells.append(CharCell(code=code, rows=pat))
                elif cells:
                    # Range exhausted — pick the closest existing pattern.
                    best_code = cells[0].code
                    best_dist = 1 << 30
                    for cell in cells:
                        d = _hamming(pat, cell.rows)
                        if d < best_dist:
                            best_dist = d
                            best_code = cell.code
                            if d == 0:
                                break
                    code = best_code
                    snapped += 1
                else:
                    # No range at all — drop to space.
                    code = 32
                    snapped += 1
            row_layout.append(code)
        layout.append(row_layout)
    return cells, layout, snapped


def _format_basic(
    char_cols: int, char_rows: int, cells: list[CharCell], layout: list[list[int]]
) -> str:
    """Generate the Extended BASIC program."""
    lines: list[str] = []
    n = 100

    def emit(s: str) -> None:
        nonlocal n
        lines.append(f"{n} {s}")
        n += 10

    emit("CALL CLEAR")
    emit("CALL SCREEN(15)")
    for cell in cells:
        emit(f'CALL CHAR({cell.code},"{cell.hex_pattern}")')

    # Centre the picture on the 32x24 TI screen.
    offset_col = max(0, (TI_SCREEN_COLS - char_cols) // 2)
    offset_row = max(0, (TI_SCREEN_ROWS - char_rows) // 2)

    # Collapse runs of identical codes on each row into one CALL HCHAR(...,count).
    for r in range(char_rows):
        c = 0
        while c < char_cols:
            code = layout[r][c]
            run_end = c
            while run_end < char_cols and layout[r][run_end] == code:
                run_end += 1
            run_len = run_end - c
            if code == 32:
                c = run_end  # CALL CLEAR filled the screen with spaces already
                continue
            ti_row = r + offset_row + 1
            ti_col = c + offset_col + 1
            if run_len == 1:
                emit(f"CALL HCHAR({ti_row},{ti_col},{code})")
            else:
                emit(f"CALL HCHAR({ti_row},{ti_col},{code},{run_len})")
            c = run_end

    emit("GOTO 9999")
    lines.append("9999 GOTO 9999")
    return "\n".join(lines) + "\n"


def bits_to_basic(
    pixel_img: PixelatedImage,
    code_start: int,
    code_end: int,
) -> ConversionResult:
    """Step 2: turn a pixelated bit matrix into a TI Extended BASIC program."""
    if code_start < 32 or code_end > 255 or code_start > code_end:
        raise ValueError(
            "character code range must satisfy 32 <= start <= end <= 255"
        )
    cells, layout, snapped = _assign_codes(
        pixel_img.char_cols, pixel_img.char_rows, pixel_img.bits, code_start, code_end
    )
    program = _format_basic(pixel_img.char_cols, pixel_img.char_rows, cells, layout)
    return ConversionResult(
        char_cols=pixel_img.char_cols,
        char_rows=pixel_img.char_rows,
        cells=cells,
        layout=layout,
        basic_program=program,
        skipped_patterns=snapped,
    )


# ---------------------------------------------------------------------------
# Backwards-compatible one-shot helper (kept for the smoke tests / CLI use)
# ---------------------------------------------------------------------------

def convert(
    pixels: bytes,
    src_width: int,
    src_height: int,
    dot_cols: int,
    dot_rows: int,
    threshold: int = 128,
    channels: int = 4,
    code_start: int = 33,
    code_end: int = 152,
) -> ConversionResult:
    """Run step 1 and step 2 together. Useful for unit tests."""
    img = pixelate(
        pixels, src_width, src_height, dot_cols, dot_rows, threshold, channels
    )
    return bits_to_basic(img, code_start, code_end)
