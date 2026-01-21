import pytest
from pathlib import Path
from PIL import Image
from fontTools.ttLib import TTFont

from backend.services.font_builder import build_emoji_font


@pytest.fixture
def sample_captures(tmp_path):
    """Create sample capture images for testing."""
    captures = {}
    for emoji in ["\U0001F600", "\U0001F601"]:
        img = Image.new("RGBA", (127, 127), (255, 200, 0, 255))
        img_path = tmp_path / f"{ord(emoji):x}.png"
        img.save(img_path)
        captures[emoji] = img_path
    return captures


def test_font_has_cbdt_table(sample_captures, tmp_path):
    font_path = build_emoji_font(sample_captures, output_dir=tmp_path)
    font = TTFont(str(font_path))
    assert 'CBDT' in font
    assert 'CBLC' in font


def test_font_has_svg_table(sample_captures, tmp_path):
    font_path = build_emoji_font(sample_captures, output_dir=tmp_path)
    font = TTFont(str(font_path))
    assert 'SVG ' in font


def test_font_metrics_are_square(sample_captures, tmp_path):
    font_path = build_emoji_font(sample_captures, output_dir=tmp_path)
    font = TTFont(str(font_path))

    ascent = font['hhea'].ascent
    descent = font['hhea'].descent
    advance = font['hmtx']['.notdef'][0]

    em_height = ascent - descent
    assert em_height == advance


def test_svg_has_glyph_ids(sample_captures, tmp_path):
    """Verify SVG documents have required glyph IDs per OpenType spec."""
    font_path = build_emoji_font(sample_captures, output_dir=tmp_path)
    font = TTFont(str(font_path))

    svg_table = font['SVG ']
    for svg_doc, start_gid, end_gid in svg_table.docList:
        # Each glyph in range must have id="glyph{glyphID}"
        for gid in range(start_gid, end_gid + 1):
            assert f'id="glyph{gid}"' in svg_doc
