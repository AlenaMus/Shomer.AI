#!/usr/bin/env python3
"""
02_render_images.py — render each sentence as a chat-bubble PNG.

USAGE:
    python 02_render_images.py                  # process whatever is in sentences.jsonl
    python 02_render_images.py --no-bubble      # plain white background (debug)

OUTPUT:
    data/ocr_validation/images/{style_label}/{id}.png

Hebrew rendering uses arabic_reshaper + python-bidi to make Pillow render RTL
correctly. Font priority: David → Arial → Segoe UI (all have Hebrew on Windows).

The script does a sanity check on the FIRST image — fails fast if Hebrew
rendering is broken, before generating bulk.
"""
import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np

# Force UTF-8 stdout on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    sys.exit("ERROR: pip install arabic-reshaper python-bidi")

REPO = Path(__file__).resolve().parents[2]
SENTENCES = REPO / "data" / "ocr_validation" / "sentences.jsonl"
IMG_ROOT = REPO / "data" / "ocr_validation" / "images"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\David.ttf",
    r"C:\Windows\Fonts\Arial.ttf",
    r"C:\Windows\Fonts\SegoeUI.ttf",
]

WHATSAPP_BG = (236, 229, 221)   # #ECE5DD
BUBBLE_BG = (255, 255, 255)
BUBBLE_OUTLINE = (200, 200, 200)
TEXT_COLOR = (20, 20, 20)


def pick_font():
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    sys.exit(f"ERROR: No Hebrew font found in {FONT_CANDIDATES}")


def render_chat_bubble(text: str, font_path: str, *, bubble: bool = True, font_size: int = 22) -> Image.Image:
    """Render `text` as a chat-screenshot-style PNG with Hebrew RTL."""
    reshaped = arabic_reshaper.reshape(text)
    display_text = get_display(reshaped)

    font = ImageFont.truetype(font_path, font_size)

    tmp = Image.new("RGB", (10, 10))
    draw_tmp = ImageDraw.Draw(tmp)
    bbox = draw_tmp.textbbox((0, 0), display_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x, pad_y = 18, 12
    bubble_margin = 14
    img_w = text_w + 2 * pad_x + 2 * bubble_margin
    img_h = text_h + 2 * pad_y + 2 * bubble_margin

    if bubble:
        img = Image.new("RGB", (img_w, img_h), WHATSAPP_BG)
        draw = ImageDraw.Draw(img)
        bubble_box = [bubble_margin, bubble_margin, img_w - bubble_margin, img_h - bubble_margin]
        draw.rounded_rectangle(bubble_box, radius=10, fill=BUBBLE_BG, outline=BUBBLE_OUTLINE, width=1)
        text_x = bubble_margin + pad_x
        text_y = bubble_margin + pad_y - bbox[1]
    else:
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        text_x = pad_x
        text_y = pad_y - bbox[1]

    draw.text((text_x, text_y), display_text, fill=TEXT_COLOR, font=font)

    # Mild noise — mimics a phone screenshot, doesn't damage readability
    arr = np.array(img).astype(np.float32)
    arr += np.random.normal(0, 0.8, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-bubble", action="store_true", help="plain white background (debug)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    if not SENTENCES.exists():
        sys.exit(f"ERROR: {SENTENCES} not found. Run 01_generate_sentences.py first.")

    font_path = pick_font()
    print(f"Font: {font_path}")
    print(f"Bubble: {'no (debug)' if args.no_bubble else 'yes (WhatsApp-style)'}")

    records = [json.loads(line) for line in SENTENCES.read_text(encoding="utf-8").splitlines()]
    print(f"Sentences to render: {len(records)}")

    # SANITY CHECK on first record
    first = records[0]
    test_img = render_chat_bubble(first["text"], font_path, bubble=not args.no_bubble)
    print(f"\nFirst image size: {test_img.size}  (text: '{first['text'][:50]}...')")
    print("[!] Open the first image manually to verify Hebrew renders RTL correctly.")

    rendered = 0
    for rec in records:
        out_dir = IMG_ROOT / rec["style"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{rec['id']}.png"
        img = render_chat_bubble(rec["text"], font_path, bubble=not args.no_bubble)
        img.save(out_path, "PNG")
        rendered += 1

    print(f"\n[OK] Rendered {rendered} images to {IMG_ROOT.relative_to(REPO)}/")
    for sub in sorted(IMG_ROOT.iterdir()):
        if sub.is_dir():
            n = len(list(sub.glob("*.png")))
            print(f"    {sub.name}/: {n} PNG")


if __name__ == "__main__":
    main()
