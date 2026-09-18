#!/usr/bin/env python3
"""Generate Reader icons. Requires Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
icons = ROOT / 'extension/icons'
icons.mkdir(exist_ok=True)
for n in (16, 32, 48, 128):
    im = Image.new('RGBA', (512, 512))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((64, 64, 448, 448), radius=80, fill='#2159ad')
    d.polygon([(148, 136), (300, 136), (300, 365), (224, 316), (148, 365)], fill='white')
    d.ellipse((235, 213, 357, 335), fill='#2159ad', outline='white', width=19)
    d.line((338, 317, 391, 370), fill='white', width=23)
    im.resize((n, n), Image.Resampling.LANCZOS).save(icons / f'{n}.png')
