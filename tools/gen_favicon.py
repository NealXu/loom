"""Generate favicon PNG/ICO for Loom (concept B: node-graph letter L).

Redraws the same geometry as loom/web/static/favicon.svg using Pillow so the
output is pixel-correct without depending on an SVG rasterizer delegate.
Run from repo root:  python tools/gen_favicon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "loom" / "web" / "static"

# Brand palette (matches favicon.svg)
BG_TOP = (30, 58, 95)      # #1e3a5f
BG_BOT = (15, 17, 23)      # #0f1117
LINE = (59, 130, 246)      # #3b82f6
NODE_FILL = (147, 197, 253)  # #93c5fd
NODE_STROKE = (15, 17, 23)  # #0f1117

# Geometry in a 64x64 design space, matching favicon.svg
STROKE_W = 4
STROKE_CX, STROKE_TOP_Y, STROKE_BOT_Y = 22, 14, 46
STROKE_END_X = 48
NODES = [(22, 14, 5), (22, 30, 5), (22, 46, 5), (35, 46, 5), (48, 46, 5)]
STROKE_W_PX = 2


def _rounded_rect(size, radius):
    """Full-alpha rounded-square mask/overlay at design scale."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=(255, 255, 255, 255))
    return img


def _vertical_gradient(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    return img


def render(size: int) -> Image.Image:
    s = size / 64.0
    # base gradient + rounded mask
    grad = _vertical_gradient(size)
    mask = _rounded_rect(size, radius=int(14 * s))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # supersample the line-art layer for crisp AA, then downscale
    ss = max(size * 4, 256)
    ssf = ss / 64.0
    art = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)

    lw = max(1, int(round(STROKE_W * ssf)))
    # vertical stem of the L
    d.line([STROKE_CX * ssf, STROKE_TOP_Y * ssf, STROKE_CX * ssf, STROKE_BOT_Y * ssf],
           fill=LINE + (255,), width=lw)
    # horizontal foot of the L
    d.line([STROKE_CX * ssf, STROKE_BOT_Y * ssf, STROKE_END_X * ssf, STROKE_BOT_Y * ssf],
           fill=LINE + (255,), width=lw)
    # nodes on top of the strokes
    for cx, cy, r in NODES:
        rr = r * ssf
        d.ellipse([cx * ssf - rr, cy * ssf - rr, cx * ssf + rr, cy * ssf + rr],
                  fill=NODE_FILL + (255,), outline=NODE_STROKE + (255,),
                  width=max(1, int(round(STROKE_W_PX * ssf))))

    art = art.resize((size, size), Image.LANCZOS)
    # clip art to rounded square
    img = Image.composite(Image.alpha_composite(img, art), img, mask)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for n in (16, 32, 48, 180, 192):
        render(n).save(OUT / f"favicon-{n}.png")
        print(f"wrote favicon-{n}.png")
    # .ico with the classic browser sizes
    render(16).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("wrote favicon.ico")


if __name__ == "__main__":
    main()
