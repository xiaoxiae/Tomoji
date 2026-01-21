import base64
import functools
import io
import logging
import struct
from pathlib import Path
from typing import Dict, Optional

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image

from backend.config import CAPTURES_DIR

logger = logging.getLogger(__name__)


def build_emoji_font(
    captures: Dict[str, Path],
    font_name: str = "Tomoji",
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Build a CBDT color bitmap font from captured emoji images.

    Heavily inspired by https://raw.githubusercontent.com/behdad/color-emoji/master/emoji_builder.py

    Args:
        captures: Dict mapping emoji characters to their image paths
        font_name: Name for the generated font
        output_dir: Directory to save the font files (defaults to CAPTURES_DIR)

    Returns:
        Path to the generated .woff2 font file
    """
    if output_dir is None:
        output_dir = CAPTURES_DIR

    logger.info(f"Starting font build with {len(captures)} emoji captures")

    upem = 1024
    ppem = 127  # Max 127 due to signed byte fields in metrics

    glyph_names = [".notdef"]
    cmap_dict = {}

    # Variation selectors that shouldn't be mapped to specific glyphs
    VARIATION_SELECTORS = {0xFE0E, 0xFE0F}  # VS15 (text), VS16 (emoji)

    for emoji in captures.keys():
        glyph_name = "emoji_" + "_".join(f"{ord(c):04X}" for c in emoji)
        glyph_names.append(glyph_name)
        # Map each codepoint in the emoji to the glyph (except variation selectors)
        for char in emoji:
            code = ord(char)
            if code not in VARIATION_SELECTORS:
                cmap_dict[code] = glyph_name

    fb = FontBuilder(upem, isTTF=True)
    fb.setupGlyphOrder(glyph_names)

    # Square em-box prevents stretching of square bitmap glyphs
    ascent = int(upem * 0.8)
    descent = ascent - upem

    empty_glyphs = {}
    for name in glyph_names:
        pen = TTGlyphPen(None)
        pen.moveTo((0, descent))
        pen.lineTo((0, ascent))
        pen.lineTo((upem, ascent))
        pen.lineTo((upem, descent))
        pen.closePath()
        empty_glyphs[name] = pen.glyph()

    fb.setupGlyf(empty_glyphs)
    fb.setupCharacterMap(cmap_dict)

    hmtx = {name: (upem, 0) for name in glyph_names}
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)

    fb.setupNameTable(
        {
            "familyName": font_name,
            "styleName": "Regular",
        }
    )

    fb.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=descent,
        usWinAscent=ascent,
        usWinDescent=-descent,
    )

    fb.setupPost()
    fb.setupHead(unitsPerEm=upem)
    font = fb.font

    logger.info("Adding CBDT/CBLC color bitmap tables...")
    _add_color_bitmap_tables(font, captures, ppem)

    logger.info("Adding SVG table for Firefox compatibility...")
    _add_svg_table(font, captures)

    ttf_path = output_dir / "tomoji.ttf"
    font.save(str(ttf_path))

    # Use brotli quality=5 (~200x faster, only 0.2% larger)
    logger.info("Converting to WOFF2...")
    import brotli

    original_compress = brotli.compress
    brotli.compress = functools.partial(original_compress, quality=5)
    try:
        woff2_path = output_dir / "tomoji.woff2"
        font.flavor = "woff2"
        font.save(str(woff2_path))
    finally:
        brotli.compress = original_compress

    logger.info(f"Font build complete: {woff2_path}")
    return woff2_path


def _add_color_bitmap_tables(font: TTFont, captures: Dict[str, Path], ppem: int):
    """Add CBDT and CBLC tables for color bitmap glyphs."""
    from fontTools.ttLib.tables import DefaultTable

    upem = font["head"].unitsPerEm
    ascent = font["hhea"].ascent
    descent = font["hhea"].descent  # Already negative

    glyph_order = font.getGlyphOrder()
    glyph_ids = {name: i for i, name in enumerate(glyph_order)}

    glyph_imgs = {}
    total = len(captures)

    for idx, (emoji, image_path) in enumerate(captures.items(), 1):
        logger.info(f"Processing bitmap {idx}/{total}: {emoji}")
        glyph_name = "emoji_" + "_".join(f"{ord(c):04X}" for c in emoji)
        glyph_id = glyph_ids.get(glyph_name)
        if glyph_id is None:
            continue

        img = Image.open(image_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        if img.size != (ppem, ppem):
            img = img.resize((ppem, ppem), Image.Resampling.LANCZOS)

        width, height = img.size
        png_buffer = io.BytesIO()
        img.save(png_buffer, format="PNG")
        png_data = png_buffer.getvalue()

        glyph_imgs[glyph_id] = (width, height, png_data)

    if not glyph_imgs:
        return

    glyphs = sorted(glyph_imgs.keys())
    first_glyph = glyphs[0]
    last_glyph = glyphs[-1]

    # Calculate strike metrics (average dimensions)
    avg_width = sum(glyph_imgs[g][0] for g in glyphs) // len(glyphs)
    avg_height = sum(glyph_imgs[g][1] for g in glyphs) // len(glyphs)
    x_ppem = y_ppem = round(avg_width * upem / upem)

    strike_ascent = round(ascent * y_ppem / upem)
    strike_descent = round(descent * y_ppem / upem)

    def write_small_glyph_metrics(width: int, height: int) -> bytes:
        return struct.pack("BBbbB", height, width, 0, strike_ascent, width)

    # CBDT format 17: smallGlyphMetrics + PNG data
    cbdt_data = bytearray()
    cbdt_data.extend(struct.pack(">I", 0x00030000))  # Version 3.0

    glyph_offsets = []
    for glyph_id in glyphs:
        width, height, png_data = glyph_imgs[glyph_id]
        offset = len(cbdt_data)
        glyph_offsets.append((glyph_id, offset))
        cbdt_data.extend(write_small_glyph_metrics(width, height))
        cbdt_data.extend(struct.pack(">I", len(png_data)))
        cbdt_data.extend(png_data)

    glyph_offsets.append((None, len(cbdt_data)))

    # CBLC table
    cblc_data = bytearray()
    cblc_data.extend(struct.pack(">I", 0x00030000))  # Version 3.0
    num_strikes = 1
    cblc_data.extend(struct.pack(">I", num_strikes))

    bitmap_size_table_size = 48
    index_subtable_array_entry_size = 8
    index_subtable_header_size = 8
    index_subtable_data_size = (len(glyphs) + 1) * 4

    index_subtable_array_offset = 8 + bitmap_size_table_size * num_strikes
    index_tables_size = (
        index_subtable_array_entry_size
        + index_subtable_header_size
        + index_subtable_data_size
    )

    cblc_data.extend(struct.pack(">I", index_subtable_array_offset))
    cblc_data.extend(struct.pack(">I", index_tables_size))
    cblc_data.extend(struct.pack(">I", 1))
    cblc_data.extend(struct.pack(">I", 0))

    # sbitLineMetrics for horizontal
    cblc_data.extend(
        struct.pack(
            "bbBbbbbbbbbb",
            strike_ascent,
            strike_descent,
            avg_width,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    )

    # sbitLineMetrics for vertical
    cblc_data.extend(
        struct.pack(
            "bbBbbbbbbbbb",
            strike_ascent,
            strike_descent,
            avg_width,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    )

    cblc_data.extend(struct.pack(">HH", first_glyph, last_glyph))
    cblc_data.extend(struct.pack("BB", x_ppem, y_ppem))
    cblc_data.extend(struct.pack("B", 32))
    cblc_data.extend(struct.pack("b", 0x01))

    cblc_data.extend(struct.pack(">HH", first_glyph, last_glyph))
    cblc_data.extend(struct.pack(">I", index_subtable_array_entry_size))

    cblc_data.extend(struct.pack(">H", 1))
    cblc_data.extend(struct.pack(">H", 17))
    image_data_offset = glyph_offsets[0][1]
    cblc_data.extend(struct.pack(">I", image_data_offset))

    for glyph_id, offset in glyph_offsets:
        cblc_data.extend(struct.pack(">I", offset - image_data_offset))

    cbdt_table = DefaultTable.DefaultTable("CBDT")
    cbdt_table.data = bytes(cbdt_data)
    font["CBDT"] = cbdt_table

    cblc_table = DefaultTable.DefaultTable("CBLC")
    cblc_table.data = bytes(cblc_data)
    font["CBLC"] = cblc_table


def _add_svg_table(font: TTFont, captures: Dict[str, Path]):
    """Add SVG table for Firefox compatibility."""
    from fontTools.ttLib.tables.S_V_G_ import table_S_V_G_

    upem = font["head"].unitsPerEm
    ascent = font["hhea"].ascent
    glyph_order = font.getGlyphOrder()
    glyph_ids = {name: i for i, name in enumerate(glyph_order)}

    svg_docs = []
    total = len(captures)
    for idx, (emoji, image_path) in enumerate(captures.items(), 1):
        logger.info(f"Processing SVG {idx}/{total}: {emoji}")
        glyph_name = "emoji_" + "_".join(f"{ord(c):04X}" for c in emoji)
        glyph_id = glyph_ids.get(glyph_name)
        if glyph_id is None:
            continue

        with open(image_path, "rb") as f:
            png_base64 = base64.b64encode(f.read()).decode("ascii")

        svg = f'''<svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="glyph{glyph_id}">
<image x="0" y="{-ascent}" width="{upem}" height="{upem}" xlink:href="data:image/png;base64,{png_base64}"/>
</g>
</svg>'''
        svg_docs.append((svg, glyph_id, glyph_id))

    if not svg_docs:
        logger.warning("No valid captures for SVG table")
        return

    svg_docs.sort(key=lambda d: d[1])
    svg_table = table_S_V_G_()
    svg_table.docList = svg_docs
    font["SVG "] = svg_table
