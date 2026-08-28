"""명품 앱 아이콘 생성기 — 다크 배경 + 골드 다이아몬드.

실행: python assets/make_icon.py
출력: assets/icon.png (1024), assets/icon.ico (Windows exe), assets/icon.icns (macOS)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        c = _lerp(top, bottom, y / (size - 1))
        for x in range(size):
            px[x, y] = c
    return img


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return m


def _diamond_polys(cx, cy, w, h):
    """다이아몬드 크라운/파빌리온 면 분할. 반환 [(poly, tone)] — tone 0~1 밝기."""
    top = cy - h * 0.42
    girdle = cy - h * 0.05
    bottom = cy + h * 0.55
    hw = w / 2
    # 크라운 테이블 좌표
    t_l, t_r = cx - hw * 0.5, cx + hw * 0.5
    g_l, g_r = cx - hw, cx + hw
    gm1, gm2 = cx - hw * 0.5, cx + hw * 0.5
    polys = [
        # 크라운
        ([(t_l, top), (t_r, top), (gm2, girdle), (gm1, girdle)], 0.95),   # 테이블
        ([(g_l, girdle), (t_l, top), (gm1, girdle)], 0.70),
        ([(t_r, top), (g_r, girdle), (gm2, girdle)], 0.60),
        ([(g_l, girdle), (cx - hw * 0.82, top + (girdle - top) * 0.35), (t_l, top)], 0.55),
        ([(t_r, top), (cx + hw * 0.82, top + (girdle - top) * 0.35), (g_r, girdle)], 0.45),
        # 파빌리온
        ([(g_l, girdle), (gm1, girdle), (cx, bottom)], 0.50),
        ([(gm1, girdle), (gm2, girdle), (cx, bottom)], 0.80),
        ([(gm2, girdle), (g_r, girdle), (cx, bottom)], 0.38),
    ]
    return polys


def build(size=SIZE) -> Image.Image:
    s = size
    bg = _vertical_gradient(s, (0x1b, 0x1b, 0x22), (0x08, 0x08, 0x0c)).convert("RGBA")

    # 은은한 골드 광원 (좌상단)
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-s * 0.2, -s * 0.25, s * 0.75, s * 0.55), fill=(212, 175, 55, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.12))
    bg.alpha_composite(glow)

    # 골드 테두리 링
    ring = ImageDraw.Draw(bg)
    pad = s * 0.055
    ring.rounded_rectangle((pad, pad, s - pad, s - pad), radius=s * 0.19,
                           outline=(214, 180, 82, 200), width=max(2, int(s * 0.012)))

    # 다이아몬드 그림자
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for poly, _ in _diamond_polys(s / 2, s / 2 + s * 0.03, s * 0.62, s * 0.62):
        sd.polygon(poly, fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 0.03))
    bg.alpha_composite(shadow)

    # 다이아몬드 면 (골드 톤)
    gold_hi = (255, 236, 160)
    gold_lo = (150, 105, 20)
    d = ImageDraw.Draw(bg)
    for poly, tone in _diamond_polys(s / 2, s / 2, s * 0.62, s * 0.62):
        d.polygon(poly, fill=_lerp(gold_lo, gold_hi, tone) + (255,),
                  outline=(90, 62, 10, 255), width=max(1, int(s * 0.004)))

    # 하이라이트 스파클
    spark = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sp = ImageDraw.Draw(spark)
    for (x, y, r) in [(s * 0.36, s * 0.30, s * 0.06), (s * 0.66, s * 0.62, s * 0.035)]:
        sp.polygon([(x, y - r), (x + r * 0.25, y), (x, y + r), (x - r * 0.25, y)], fill=(255, 255, 255, 230))
        sp.polygon([(x - r, y), (x, y - r * 0.25), (x + r, y), (x, y + r * 0.25)], fill=(255, 255, 255, 230))
    spark = spark.filter(ImageFilter.GaussianBlur(s * 0.003))
    bg.alpha_composite(spark)

    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(bg, (0, 0), _rounded_mask(s, s * 0.22))
    return out


def main():
    img = build()
    png = os.path.join(HERE, "icon.png")
    img.save(png)
    ico = os.path.join(HERE, "icon.ico")
    img.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", png, ico)

    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as td:
            iconset = os.path.join(td, "icon.iconset")
            os.makedirs(iconset)
            for n in (16, 32, 128, 256, 512):
                img.resize((n, n), Image.LANCZOS).save(os.path.join(iconset, f"icon_{n}x{n}.png"))
                img.resize((n * 2, n * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{n}x{n}@2x.png"))
            icns = os.path.join(HERE, "icon.icns")
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
            print("wrote", icns)


if __name__ == "__main__":
    main()
