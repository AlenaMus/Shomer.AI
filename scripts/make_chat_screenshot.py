"""Generate a realistic WhatsApp-style Hebrew chat screenshot for OCR testing.

Renders a few message bubbles (one clearly offensive) onto a phone-sized canvas
so we can POST it to POST /v1/monitor/image and exercise the REAL Tesseract OCR
path end-to-end — the automated tests stub OCR, so this is the first real check.

Usage:
    python scripts/make_chat_screenshot.py [out.png]
"""
from __future__ import annotations

import sys
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont


def rtl(s: str) -> str:
    """Reorder logical Hebrew into visual RTL order (PIL has no bidi shaping)."""
    return get_display(s)

OUT = sys.argv[1] if len(sys.argv) > 1 else "scripts/_chat_screenshot.png"

# Phone-ish portrait canvas.
W, H = 1080, 2160
BG = (230, 221, 212)          # WhatsApp wallpaper beige
INCOMING = (255, 255, 255)    # left bubbles (received)
OUTGOING = (220, 248, 198)    # right bubbles (sent)
TEXT = (20, 20, 20)

img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 52)
small = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 30)

# Top app bar.
draw.rectangle([0, 0, W, 130], fill=(7, 94, 84))
# RTL-align the title to the right edge.
title = rtl("קבוצת הכיתה")
tw_title = draw.textlength(title, font=font)
draw.text((W - 40 - tw_title, 45), title, font=font, fill=(255, 255, 255))

# Messages: (text, is_outgoing). Hebrew is RTL; Tesseract heb handles it.
messages = [
    ("היי מה קורה", False),
    ("בסדר גמור ואצלך", True),
    ("כולם שונאים אותך תתאבד", False),   # clear cyberbullying — should flag
    ("נתראה מחר בבית ספר", True),
]

y = 200
for text, outgoing in messages:
    bubble = OUTGOING if outgoing else INCOMING
    visual = rtl(text)
    tw = draw.textlength(visual, font=font)
    pad = 36
    bw = int(tw) + pad * 2
    bh = 110
    if outgoing:
        x1 = W - 40 - bw
    else:
        x1 = 40
    x2 = x1 + bw
    draw.rounded_rectangle([x1, y, x2, y + bh], radius=28, fill=bubble)
    draw.text((x1 + pad, y + 28), visual, font=font, fill=TEXT)
    draw.text((x1 + 16, y + bh - 38), "10:42", font=small, fill=(120, 120, 120))
    y += bh + 40

img.save(OUT, "PNG")
print(f"wrote {OUT}  ({W}x{H})")
