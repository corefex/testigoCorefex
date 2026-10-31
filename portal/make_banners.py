"""Generate the promo banner PNGs for the Distribuidora X portal.

  .venv/bin/python -m portal.make_banners

Produces portal/static/:
  banner_clean.png        the plain promo (used by clean, A1 and A3)
  banner_a2_v1..v5.png    the same promo with the injected line painted in,
                          in a color almost identical to the background so a
                          person barely sees it but a model reading the pixels
                          can. This is the A2 attack surface.

All text is fake. The injected line names the placeholder attacker account.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from portal import scenarios as sc

W, H = 300, 260
BG = (243, 231, 201)        # warm banner background
INK = (59, 46, 18)          # dark brown for the visible promo
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
STATIC = Path(__file__).resolve().parent / "static"


def font(name, size):
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def draw_promo(d):
    """The visible promo, identical on every banner."""
    d.text((18, 18), "THIS WEEK", font=font("Arial Bold.ttf", 13), fill=(122, 90, 30))
    d.text((18, 40), "Fresh stock.", font=font("Arial Bold.ttf", 24), fill=INK)
    d.text((18, 70), "New: rice 10 kg.", font=font("Arial Bold.ttf", 24), fill=INK)
    # three simple product blocks along the bottom
    d.rectangle([18, 150, 70, 224], outline=INK, width=2, fill=(255, 255, 255))
    d.rectangle([84, 130, 136, 224], outline=INK, width=2, fill=(226, 201, 140))
    d.rectangle([150, 166, 198, 224], outline=INK, width=2, fill=(217, 180, 90))


def faint(delta):
    """A color delta channels away from the background - barely visible."""
    return tuple(max(0, c - delta) for c in BG)


def inject_line(d, variant):
    cfg = sc.A2_VARIANTS[variant]
    text = sc.WORDING[variant]
    f = font("Arial.ttf", cfg["size"])
    fill = faint(cfg["delta"])
    if cfg["position"] == "top":
        xy = (14, 6)
    elif cfg["position"] == "middle":
        xy = (14, 118)
    else:  # bottom
        xy = (14, 240)
    d.text(xy, text, font=f, fill=fill)


def main():
    STATIC.mkdir(parents=True, exist_ok=True)

    clean = Image.new("RGB", (W, H), BG)
    draw_promo(ImageDraw.Draw(clean))
    clean.save(STATIC / "banner_clean.png")
    print("wrote banner_clean.png")

    for v in sc.VARIANTS:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        draw_promo(d)
        inject_line(d, v)
        out = "banner_a2_v%d.png" % v
        img.save(STATIC / out)
        print("wrote", out)


if __name__ == "__main__":
    main()
