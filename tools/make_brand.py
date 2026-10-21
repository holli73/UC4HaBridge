#!/usr/bin/env python3
"""Generate brand images (HA >= 2026.3 loads them from custom_components/<domain>/brand/).

    .venv/bin/python tools/make_brand.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "automic_heating" / "brand"
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
WARM_TOP = (255, 112, 67)  # orange
WARM_BOTTOM = (211, 47, 47)  # red
WHITE = (255, 255, 255, 255)


def gradient_tile(size: int) -> Image.Image:
    """Rounded square with a vertical warm gradient."""
    grad = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(WARM_TOP, WARM_BOTTOM))
        draw.line([(0, y), (size, y)], fill=color + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=255)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(grad, mask=mask)
    return tile


def thermometer(draw: ImageDraw.ImageDraw, cx: float, top: float, height: float, color) -> None:
    """Thermometer glyph: stem with scale marks and a bulb."""
    w = height * 0.22
    bulb_r = w * 0.95
    stem_bottom = top + height - bulb_r * 1.6
    line = max(2, round(w * 0.22))
    draw.rounded_rectangle([cx - w / 2, top, cx + w / 2, stem_bottom + bulb_r], radius=w / 2,
                           outline=color, width=line)
    draw.ellipse([cx - bulb_r, top + height - 2 * bulb_r, cx + bulb_r, top + height], fill=color)
    inner = w * 0.22
    draw.rounded_rectangle([cx - inner, top + height * 0.35, cx + inner, top + height - bulb_r],
                           radius=inner, fill=color)
    for i in range(3):
        y = top + height * (0.18 + i * 0.13)
        draw.line([(cx - w / 2 - w * 0.55, y), (cx - w / 2 - line, y)], fill=color, width=line)


def icon(size: int) -> Image.Image:
    img = gradient_tile(size)
    draw = ImageDraw.Draw(img)
    thermometer(draw, size * 0.31, size * 0.17, size * 0.66, WHITE)
    font = ImageFont.truetype(FONT, round(size * 0.22), index=1)  # bold
    draw.text((size * 0.69, size * 0.50), "UC4", font=font, fill=WHITE, anchor="mm")
    return img


def logo(height: int, text_color) -> Image.Image:
    """Icon tile + wordmark, transparent background."""
    tile = icon(height)
    font = ImageFont.truetype(FONT, round(height * 0.34), index=1)
    small = ImageFont.truetype(FONT, round(height * 0.2), index=0)
    x = height * 1.15
    text_w = max(font.getlength("Automic"), small.getlength("Heating bridge"))
    width = round(x + text_w + height * 0.08)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    img.paste(tile, (0, 0), tile)
    draw = ImageDraw.Draw(img)
    draw.text((x, height * 0.44), "Automic", font=font, fill=text_color, anchor="ls")
    draw.text((x, height * 0.78), "Heating bridge", font=small, fill=text_color, anchor="ls")
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for scale, suffix in ((1, ""), (2, "@2x")):
        ico = icon(256 * scale)
        ico.save(OUT / f"icon{suffix}.png", optimize=True)
        ico.save(OUT / f"dark_icon{suffix}.png", optimize=True)
        logo(256 * scale, (33, 33, 33, 255)).save(OUT / f"logo{suffix}.png", optimize=True)
        logo(256 * scale, (240, 240, 240, 255)).save(OUT / f"dark_logo{suffix}.png", optimize=True)
    print("written:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
