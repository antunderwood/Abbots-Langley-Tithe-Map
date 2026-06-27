#!/usr/bin/env python3
"""Draft mosaic of the 7 stitched areas, placed per the source page's layout, for visual review.

Layout comes from the clickable image-map on tithemapview*.htm (Completemap_small.jpg, 180x272):
two columns - left col areas 5,6,7 top-to-bottom; right col areas 1,2,3,4 top-to-bottom.
Boxes are approximate (they were drawn for click targets, not precise bounds), so this is a
LAYOUT/ORIENTATION review, not a seamless mosaic. Output: scratch preview JPEG.

Usage: python3 scripts/preview_mosaic.py OUT.jpg
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SRC = os.path.join(os.path.dirname(__file__), "..", "source_images")
NAME = "IR30-15-1_%d_Abbotts_Langley_Herts.jpg"

# area -> (x1, y1, x2, y2) in 180x272 thumbnail space
BOXES = {
    5: (0, 0, 68, 90), 6: (0, 90, 69, 180), 7: (0, 180, 71, 272),
    1: (68, 0, 180, 70), 2: (68, 70, 180, 134), 3: (68, 134, 180, 205), 4: (69, 204, 180, 272),
}
SCALE = 7  # thumbnail px -> preview px


def main(out):
    canvas = Image.new("RGB", (180 * SCALE, 272 * SCALE), "#dddddd")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 80)
    except OSError:
        font = ImageFont.load_default()

    for area, (x1, y1, x2, y2) in BOXES.items():
        path = os.path.join(SRC, NAME % area)
        bx, by = x1 * SCALE, y1 * SCALE
        bw, bh = (x2 - x1) * SCALE, (y2 - y1) * SCALE
        if os.path.exists(path):
            with Image.open(path) as im:
                canvas.paste(im.resize((bw, bh)), (bx, by))
        else:
            draw.rectangle([bx, by, bx + bw, by + bh], fill="#bbbbbb")
        draw.rectangle([bx, by, bx + bw - 1, by + bh - 1], outline="red", width=3)
        # area number badge
        draw.rectangle([bx + 6, by + 6, bx + 96, by + 96], fill="white", outline="red", width=3)
        draw.text((bx + 30, by + 14), str(area), fill="red", font=font)

    canvas.save(out, quality=88)
    print(f"wrote {out} ({canvas.size[0]}x{canvas.size[1]})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mosaic_preview.jpg")
