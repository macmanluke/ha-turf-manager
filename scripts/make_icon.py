"""Draw the Turf Manager brand icon: a green badge with mowing stripes, a sun and a grass tuft.

Usage: python scripts/make_icon.py custom_components/turf_manager/brand
(needs Pillow; it is installed with Home Assistant in the test venv)
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

SIZE = 2048
out_dir = Path(sys.argv[1])


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=False))


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def blade(cx, base_y, height, lean, width):
    """Polygon for a curved, tapering blade of grass."""
    tip = (cx + lean, base_y - height)
    ctrl = (cx - lean * 0.05, base_y - height * 0.62)
    left, right = [], []
    steps = 60
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * cx + 2 * (1 - t) * t * ctrl[0] + t**2 * tip[0]
        y = (1 - t) ** 2 * base_y + 2 * (1 - t) * t * ctrl[1] + t**2 * tip[1]
        dx = 2 * (1 - t) * (ctrl[0] - cx) + 2 * t * (tip[0] - ctrl[0])
        dy = 2 * (1 - t) * (ctrl[1] - base_y) + 2 * t * (tip[1] - ctrl[1])
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n
        w = width * (1 - t) ** 0.85 / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


# Badge: rounded square with a vertical gradient.
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=int(SIZE * 0.23), fill=255)

top, bottom = hex_rgb("#43A047"), hex_rgb("#1B5E20")
badge = Image.new("RGBA", (SIZE, SIZE))
draw = ImageDraw.Draw(badge)
for y in range(SIZE):
    draw.line([(0, y), (SIZE, y)], fill=(*lerp(top, bottom, y / SIZE), 255))

# Mowing stripes: wide diagonal bands, slightly lighter.
stripes = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
sd = ImageDraw.Draw(stripes)
band = SIZE // 5
for i in range(-6, 8, 2):
    x0 = i * band
    sd.polygon([(x0, SIZE), (x0 + band, SIZE), (x0 + band + SIZE * 0.6, 0), (x0 + SIZE * 0.6, 0)], fill=(255, 255, 255, 22))
badge = Image.alpha_composite(badge, stripes)

# Sun: heat is what drives growing degree days.
sun = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
sund = ImageDraw.Draw(sun)
cx, cy, r = SIZE * 0.71, SIZE * 0.28, SIZE * 0.10
for i in range(14, 0, -1):  # soft glow
    rr = r * (1 + i * 0.06)
    sund.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 236, 140, 7))
sund.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*hex_rgb("#FFD54F"), 255))
badge = Image.alpha_composite(badge, sun)

# Grass tuft rising from the bottom: back blades darker, front blades lighter.
grass = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
gd = ImageDraw.Draw(grass)
base = SIZE * 1.04
blades = [
    # cx, height, lean, width, colour
    (0.22, 0.42, -0.16, 0.12, "#7CB342"),
    (0.78, 0.40, 0.17, 0.12, "#7CB342"),
    (0.34, 0.58, -0.17, 0.14, "#9CCC65"),
    (0.66, 0.55, 0.15, 0.14, "#9CCC65"),
    (0.43, 0.70, -0.08, 0.15, "#C5E1A5"),
    (0.57, 0.66, 0.10, 0.15, "#AED581"),
    (0.50, 0.50, -0.02, 0.15, "#DCEDC8"),
]
for cx_, h, lean, w, colour in blades:
    gd.polygon(
        blade(SIZE * cx_, base, SIZE * h, SIZE * lean, SIZE * w),
        fill=(*hex_rgb(colour), 255),
    )
badge = Image.alpha_composite(badge, grass)

# Clip to the rounded square.
alpha = ImageChops.multiply(badge.getchannel("A"), mask)
badge.putalpha(alpha)

out_dir.mkdir(parents=True, exist_ok=True)
for name, px in (("icon.png", 256), ("icon@2x.png", 512)):
    badge.resize((px, px), Image.LANCZOS).save(out_dir / name, optimize=True)

# Preview on light and dark backgrounds.
preview = Image.new("RGBA", (1100, 560), (250, 250, 250, 255))
dark = Image.new("RGBA", (550, 560), (28, 28, 28, 255))
preview.paste(dark, (550, 0))
icon = badge.resize((256, 256), Image.LANCZOS)
small = badge.resize((48, 48), Image.LANCZOS)
for x0 in (0, 550):
    preview.alpha_composite(icon, (x0 + 60, 150))
    preview.alpha_composite(small, (x0 + 400, 254))
preview.save(out_dir / "preview.png")
print("written", sorted(p.name for p in out_dir.iterdir()))
