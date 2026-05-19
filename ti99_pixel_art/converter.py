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

# TI character codes 0..31 are reserved for control characters; code 32 is
# the space character that CALL CLEAR fills the screen with. We therefore
# never redefine codes <= 32 — the user-facing 'Char code start' is clamped
# to MIN_USER_CODE.
SPACE_CODE = 32
MIN_USER_CODE = 33

# Private sentinel for 'this cell is background and need not be placed'. Kept
# distinct from SPACE_CODE so a user-assigned code 32 would never collide
# with the skip-placements optimisation in _format_basic.
_BACKGROUND = -1


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

def _luminance_per_pixel(
    pixels: bytes, width: int, height: int, channels: int
) -> list[int]:
    """Flatten the BGRA buffer into a length-(width*height) list of luminance
    values in 0..255. Fully transparent pixels are clamped to 255 so they
    read as background. Computed once per pixelate() call and then summed
    over cell rectangles, which is far cheaper than re-reading the BGRA
    buffer for every cell.
    """
    out = [0] * (width * height)
    if channels >= 3:
        for i in range(width * height):
            p = i * channels
            b = pixels[p]
            g = pixels[p + 1]
            r = pixels[p + 2]
            a = pixels[p + 3] if channels >= 4 else 255
            if a < 16:
                out[i] = 255  # transparent reads as background
            else:
                out[i] = (299 * r + 587 * g + 114 * b) // 1000
    else:
        for i in range(width * height):
            out[i] = pixels[i * channels]
    return out


def pixelate(
    pixels: bytes,
    src_width: int,
    src_height: int,
    dot_cols: int,
    dot_rows: int,
    threshold: int = 128,
    channels: int = 4,
) -> PixelatedImage:
    """Step 1: divide the source rect into ``dot_cols`` x ``dot_rows`` cells
    of their natural pixel size (``src_width / dot_cols`` x
    ``src_height / dot_rows``) and pick black or white for each cell from
    the AVERAGE LUMINANCE of all pixels falling inside it. The source image
    is never resampled or rescaled — every source pixel contributes exactly
    once to exactly one cell.

    ``dot_cols`` and ``dot_rows`` are rounded down to a multiple of 8 and
    clamped to the TI screen (256x192 dots) so the picture decomposes
    cleanly into 8x8 character cells.
    """
    if dot_cols < 8 or dot_rows < 8:
        raise ValueError("dot columns and rows must be at least 8")
    dot_cols = min(DOT_MAX_W, (dot_cols // 8) * 8)
    dot_rows = min(DOT_MAX_H, (dot_rows // 8) * 8)
    if src_width <= 0 or src_height <= 0:
        raise ValueError("source image has zero size")
    if len(pixels) < src_width * src_height * channels:
        raise ValueError("pixel buffer is smaller than width*height*channels")
    if src_width < dot_cols or src_height < dot_rows:
        raise ValueError(
            "source rect is smaller than the dot grid — pick fewer dots, or "
            "make the selection / canvas larger"
        )

    lum = _luminance_per_pixel(pixels, src_width, src_height, channels)

    # Cell boundaries computed as ``(idx * src) // dots`` so every source
    # pixel falls into exactly one cell with no overlap or gaps. Cells on
    # the right/bottom edges may be one source pixel wider/taller than the
    # rest when the dot grid doesn't divide the source size evenly.
    x_bounds = [(cx * src_width) // dot_cols for cx in range(dot_cols + 1)]
    y_bounds = [(cy * src_height) // dot_rows for cy in range(dot_rows + 1)]

    bits = [[0] * dot_cols for _ in range(dot_rows)]
    for cy in range(dot_rows):
        y0 = y_bounds[cy]
        y1 = y_bounds[cy + 1]
        if y1 <= y0:
            y1 = y0 + 1
        bit_row = bits[cy]
        for cx in range(dot_cols):
            x0 = x_bounds[cx]
            x1 = x_bounds[cx + 1]
            if x1 <= x0:
                x1 = x0 + 1
            total = 0
            count = 0
            for yy in range(y0, y1):
                row_off = yy * src_width
                for xx in range(x0, x1):
                    total += lum[row_off + xx]
                    count += 1
            avg = total // count if count else 255
            bit_row[cx] = 1 if avg < threshold else 0

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
    ``[code_start..code_end]``. All-zero (background) cells are tagged with
    the private ``_BACKGROUND`` sentinel and never consume a code slot.
    Returns ``(cells, layout, snapped)`` where ``snapped`` counts cells that
    had to merge onto a neighbour because the code range was exhausted.
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
                row_layout.append(_BACKGROUND)
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
                    # No range at all — drop to background (will not be placed).
                    code = _BACKGROUND
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
    # Background cells (sentinel value) are skipped because CALL CLEAR has
    # already filled the screen with code 32 (space).
    for r in range(char_rows):
        c = 0
        while c < char_cols:
            code = layout[r][c]
            run_end = c
            while run_end < char_cols and layout[r][run_end] == code:
                run_end += 1
            run_len = run_end - c
            if code == _BACKGROUND:
                c = run_end
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
    """Step 2: turn a pixelated bit matrix into a TI Extended BASIC program.

    ``code_start`` is silently clamped up to ``MIN_USER_CODE`` (33) because
    code 32 is the space character that CALL CLEAR fills the screen with —
    redefining it would mean every 'untouched' cell on the TI screen shows
    the redefined pattern instead of staying blank.
    """
    if code_end > 255 or code_start > code_end:
        raise ValueError(
            f"character code range must satisfy start <= end <= 255 "
            f"(got start={code_start}, end={code_end})"
        )
    if code_start < MIN_USER_CODE:
        code_start = MIN_USER_CODE
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
