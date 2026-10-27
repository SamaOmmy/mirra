"""Draws the Mirra logo and writes every size the apps need.

    python packaging/make_logo.py

Writes samantha_mirror/assets/mirra.ico (the Windows programs and window), mirra-256.png and mirra-64.png (shown
inside the window), and docs/logo.png. The Android icons are vector drawables in android/res/drawable that follow
the same geometry (see SHAPES below), so they stay sharp at every size.

The logo: a rounded tile with a violet-to-cyan gradient, and on it a PC screen with a phone in front of it.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
VIOLET, CYAN = (124, 92, 255), (34, 211, 238)
SIZE = 1024
# In a 1024 square: the screen, its stand, and the phone (x0, y0, x1, y1, corner radius).
SCREEN = (196, 270, 760, 640, 64)
STAND = (420, 640, 536, 712)
BASE = (336, 712, 620, 760, 24)
PHONE = (600, 430, 828, 830, 52)
STROKE = 54


def gradient(size: int) -> Image.Image:
    """Diagonal violet (top left) to cyan (bottom right)."""
    import numpy as np
    xs = np.arange(size, dtype=np.float32)
    t = ((xs[None, :] + xs[:, None]) / (2 * (size - 1)))[..., None]
    rgb = np.array(VIOLET, np.float32) * (1 - t) + np.array(CYAN, np.float32) * t
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def draw(size: int = SIZE) -> Image.Image:
    s = size / SIZE
    big = 4   # draw large, shrink: smooth edges
    w = size * big
    k = s * big
    tile_mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, w - 1, w - 1), radius=int(230 * k), fill=255)
    tile = gradient(w)

    glyph = Image.new("L", (w, w), 0)
    g = ImageDraw.Draw(glyph)
    x0, y0, x1, y1, r = SCREEN
    g.rounded_rectangle([v * k for v in (x0, y0, x1, y1)], radius=r * k, outline=255, width=int(STROKE * k))
    g.rectangle([v * k for v in STAND], fill=255)
    bx0, by0, bx1, by1, br = BASE
    g.rounded_rectangle([v * k for v in (bx0, by0, bx1, by1)], radius=br * k, fill=255)
    # the phone stands in front: clear what is behind it, then draw it
    px0, py0, px1, py1, pr = PHONE
    gap = 34
    hole = Image.new("L", (w, w), 0)
    ImageDraw.Draw(hole).rounded_rectangle([(px0 - gap) * k, (py0 - gap) * k, (px1 + gap) * k, (py1 + gap) * k],
                                           radius=(pr + gap) * k, fill=255)
    glyph = ImageChops.subtract(glyph, hole)
    g = ImageDraw.Draw(glyph)
    g.rounded_rectangle([px0 * k, py0 * k, px1 * k, py1 * k], radius=pr * k, outline=255, width=int(STROKE * k))
    g.rounded_rectangle([(px0 + 84) * k, (py1 - 92) * k, (px1 - 84) * k, (py1 - 70) * k], radius=11 * k, fill=255)

    out = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    out.paste(tile, (0, 0), tile_mask)
    white = Image.new("RGBA", (w, w), (255, 255, 255, 255))
    out.paste(white, (0, 0), ImageChops.multiply(glyph, tile_mask))
    return out.resize((size, size), Image.LANCZOS)


# -- Android: the same drawing as vector drawables -------------------------------------------------------
def _rr(x0, y0, x1, y1, r):
    """A closed rounded rectangle as SVG path data."""
    return (f"M{x0 + r:.2f},{y0:.2f} H{x1 - r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x1:.2f},{y0 + r:.2f} V{y1 - r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 1 {x1 - r:.2f},{y1:.2f} H{x0 + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x0:.2f},{y1 - r:.2f} "
            f"V{y0 + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x0 + r:.2f},{y0:.2f} Z")


def glyph_paths(tx):
    """(stroke paths, fill paths) of the white glyph, in the coordinates tx(x, y) -> (x, y) and scale tx.s."""
    s = tx.s
    half = STROKE / 2
    x0, y0, x1, y1, r = SCREEN
    gap = 34
    cut_x = PHONE[0] - gap          # the screen outline stops where the phone (and its gap) begins
    cut_y = PHONE[1] - gap
    ax0, ay0, ax1, ay1, ar = x0 + half, y0 + half, x1 - half, y1 - half, r - half

    def p(x, y):
        X, Y = tx(x, y)
        return f"{X:.2f},{Y:.2f}"
    R = ar * s
    screen = (f"M{p(cut_x, ay1)} H{tx(ax0 + ar, 0)[0]:.2f} A{R:.2f},{R:.2f} 0 0 1 {p(ax0, ay1 - ar)} "
              f"V{tx(0, ay0 + ar)[1]:.2f} A{R:.2f},{R:.2f} 0 0 1 {p(ax0 + ar, ay0)} H{tx(ax1 - ar, 0)[0]:.2f} "
              f"A{R:.2f},{R:.2f} 0 0 1 {p(ax1, ay0 + ar)} V{tx(0, cut_y)[1]:.2f}")
    px0, py0, px1, py1, pr = PHONE
    a, b = tx(px0 + half, py0 + half), tx(px1 - half, py1 - half)
    phone = _rr(a[0], a[1], b[0], b[1], (pr - half) * s)
    sx0, sy0 = tx(STAND[0], STAND[1] - 4)
    sx1, sy1 = tx(STAND[2], STAND[3] + 4)
    stand = f"M{sx0:.2f},{sy0:.2f} H{sx1:.2f} V{sy1:.2f} H{sx0:.2f} Z"
    bx0, by0, _, by1, br = BASE
    c, d = tx(bx0, by0), tx(cut_x, by1)
    BR = br * s
    base = (f"M{c[0] + BR:.2f},{c[1]:.2f} H{d[0]:.2f} V{d[1]:.2f} H{c[0] + BR:.2f} "
            f"A{BR:.2f},{BR:.2f} 0 0 1 {c[0]:.2f},{d[1] - BR:.2f} V{c[1] + BR:.2f} A{BR:.2f},{BR:.2f} 0 0 1 {c[0] + BR:.2f},{c[1]:.2f} Z")
    e, f = tx(px0 + 84, py1 - 92), tx(px1 - 84, py1 - 70)
    bar = _rr(e[0], e[1], f[0], f[1], 11 * s)
    return [screen, phone], [stand, base, bar]


class _Tx:
    """Maps the 1024 drawing so that its glyph is `width` wide and centred on (cx, cy)."""

    def __init__(self, width, cx, cy, offset_x=0.0, offset_y=0.0):
        gx0, gy0, gx1, gy1 = SCREEN[0], SCREEN[1], PHONE[2], PHONE[3]
        self.s = width / (gx1 - gx0)
        self.mx, self.my = (gx0 + gx1) / 2, (gy0 + gy1) / 2
        self.cx, self.cy = cx + offset_x, cy + offset_y

    def __call__(self, x, y):
        return self.cx + (x - self.mx) * self.s, self.cy + (y - self.my) * self.s


def _vector(size, body, extra_ns=""):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!-- written by packaging/make_logo.py -->\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android"{extra_ns}\n'
            f'    android:width="{size}dp" android:height="{size}dp"\n'
            f'    android:viewportWidth="{size}" android:viewportHeight="{size}">\n{body}</vector>\n')


def _glyph_xml(tx, color):
    strokes, fills = glyph_paths(tx)
    w = STROKE * tx.s
    out = ""
    for d in strokes:
        out += (f'    <path android:pathData="{d}" android:strokeColor="{color}" android:strokeWidth="{w:.2f}" '
                f'android:strokeLineCap="butt" android:strokeLineJoin="round" />\n')
    for d in fills:
        out += f'    <path android:pathData="{d}" android:fillColor="{color}" />\n'
    return out


def _gradient(x0, y0, x1, y1):
    return (f'        <aapt:attr name="android:fillColor">\n'
            f'            <gradient android:type="linear" android:startX="{x0}" android:startY="{y0}" '
            f'android:endX="{x1}" android:endY="{y1}">\n'
            f'                <item android:offset="0" android:color="#FF7C5CFF" />\n'
            f'                <item android:offset="1" android:color="#FF22D3EE" />\n'
            f'            </gradient>\n        </aapt:attr>\n')


def android() -> None:
    res = ROOT / "android" / "res"
    drawable, mipmap = res / "drawable", res / "mipmap-anydpi"
    drawable.mkdir(parents=True, exist_ok=True)
    mipmap.mkdir(parents=True, exist_ok=True)
    aapt = '\n    xmlns:aapt="http://schemas.android.com/aapt"'
    # adaptive icon: 108 x 108, the glyph inside the 66 dp safe circle
    (drawable / "ic_launcher_background.xml").write_text(_vector(108, (
        '    <path android:pathData="M0,0 H108 V108 H0 Z">\n' + _gradient(0, 0, 108, 108) + '    </path>\n'), aapt), encoding="utf-8")
    tx = _Tx(54, 54, 54)
    (drawable / "ic_launcher_foreground.xml").write_text(_vector(108, _glyph_xml(tx, "#FFFFFFFF")), encoding="utf-8")
    (drawable / "ic_launcher_monochrome.xml").write_text(_vector(108, _glyph_xml(tx, "#FF000000")), encoding="utf-8")
    (mipmap / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<!-- written by packaging/make_logo.py -->\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@drawable/ic_launcher_background" />\n'
        '    <foreground android:drawable="@drawable/ic_launcher_foreground" />\n'
        '    <monochrome android:drawable="@drawable/ic_launcher_monochrome" />\n'
        '</adaptive-icon>\n', encoding="utf-8")
    # notification icon: white glyph only
    (drawable / "ic_notify.xml").write_text(_vector(24, _glyph_xml(_Tx(20, 12, 12), "#FFFFFFFF")), encoding="utf-8")
    # the logo tile shown inside the apps
    tile = 96
    body = (f'    <path android:pathData="{_rr(0, 0, tile, tile, tile * 230 / 1024)}">\n'
            + _gradient(0, 0, tile, tile) + '    </path>\n' + _glyph_xml(_Tx(tile * 632 / 1024, tile / 2, tile * 550 / 1024), "#FFFFFFFF"))
    (drawable / "logo.xml").write_text(_vector(tile, body, aapt), encoding="utf-8")
    old = drawable / "icon.xml"
    if old.exists():
        old.unlink()
    print("wrote", drawable)


def main() -> None:
    assets = ROOT / "samantha_mirror" / "assets"
    assets.mkdir(exist_ok=True)
    logo = draw(1024)
    logo.save(ROOT / "docs" / "logo.png")
    draw(256).save(assets / "mirra-256.png")
    draw(64).save(assets / "mirra-64.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    logo.save(assets / "mirra.ico", sizes=[(n, n) for n in sizes])
    logo.save(ROOT / "packaging" / "mirra.ico", sizes=[(n, n) for n in sizes])
    print("wrote", assets)
    android()


if __name__ == "__main__":
    main()
