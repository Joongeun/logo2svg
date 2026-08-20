#!/usr/bin/env python3
"""Semantic tracing example: the SnapCycle logo.

The generic CLI (../../logo2svg.py) emits anonymous layers. This script shows
the hand-tuned step that turns them into *meaningful* groups: it knows this
image contains a phone, three speed lines, a couch, a lounging stick figure,
and a cap, picks each connected component by size/position, and stacks them in
occlusion order. The result animates naturally — e.g. translate #couch,
#figure and #cap together to slide the sofa out of the phone.

Run from this directory:  python3 semantic_trace.py
"""
import os
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'logo.png')
OUT = os.path.join(HERE, 'logo-semantic.svg')

DARK = '#15211c'
GREEN = '#0d6b48'
MINT = '#e2ece6'

im = Image.open(SRC).convert('RGBA')
a = np.array(im).astype(int)
H, W = a.shape[:2]
rgb = a[..., :3]
opaque = a[..., 3] >= 128

anchors = [(21, 33, 28), (13, 107, 72), (230, 239, 233)]  # dark, green, mint
cls = np.argmin(
    np.stack([((rgb - np.array(c)) ** 2).sum(-1) for c in anchors], -1), -1)
dark = opaque & (cls == 0)
green = opaque & (cls == 1)
mint = opaque & (cls == 2)

lab_d, _ = ndimage.label(dark)
lab_g, _ = ndimage.label(green)
lab_m, _ = ndimage.label(mint)


def comps(lab, min_size=1000):
    """[(size, cx, cy, mask)] for components >= min_size, largest first."""
    n = lab.max()
    sizes = ndimage.sum(lab > 0, lab, range(1, n + 1))
    out = []
    for i in range(1, n + 1):
        if sizes[i - 1] < min_size:
            continue
        m = lab == i
        ys, xs = np.where(m)
        out.append((int(sizes[i - 1]), xs.mean(), ys.mean(), m))
    out.sort(key=lambda t: -t[0])
    return out


# --- pick each semantic piece by size and position (671x600 source) ---
dark_c = comps(lab_d)
phone_body = dark_c[0][3]                                   # largest dark blob
figure = next(m for s, cx, cy, m in dark_c[1:] if cx > 330)
notch = next(m for s, cx, cy, m in dark_c[1:] if cx <= 330)

green_c = comps(lab_g)
couch_out = green_c[0][3]                                   # largest green blob
cap = next(m for s, cx, cy, m in green_c[1:] if cy < 110 and cx > 450)
speeds = sorted([(cy, m) for s, cx, cy, m in green_c[1:] if cx < 280],
                key=lambda t: t[0])
assert len(speeds) == 3, f'expected 3 speed lines, got {len(speeds)}'
speed1, speed2, speed3 = (m for _, m in speeds)

mint_c = comps(lab_m, min_size=500)
screen = mint_c[0][3]                                       # largest mint blob
head_fill = next(m for s, cx, cy, m in mint_c[1:] if cy < 115 and cx > 450)

# couch cushions: every real mint component that isn't screen or head fill
cushions = np.zeros_like(mint)
sizes = ndimage.sum(mint, lab_m, range(1, lab_m.max() + 1))
for i, sl in enumerate(ndimage.find_objects(lab_m), start=1):
    if sizes[i - 1] < 40 or sl is None:
        continue
    hgt, wid = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
    if wid <= 3 or hgt <= 3:      # 1-2px trim-artifact strips
        continue
    m = lab_m == i
    if (m & screen).any() or (m & head_fill).any():
        continue
    cushions |= m

# --- z-order (bottom -> top), grouped semantically ---
groups = [
    ('phone', [('phone-body', phone_body, DARK),
               ('screen', screen, MINT),
               ('notch', notch, DARK)]),
    ('speed-lines', [('speed-line-1', speed1, GREEN),
                     ('speed-line-2', speed2, GREEN),
                     ('speed-line-3', speed3, GREEN)]),
    ('couch', [('cushions', cushions, MINT),
               ('couch-outline', couch_out, GREEN)]),
    ('figure', [('head-fill', head_fill, MINT),
                ('figure-body', figure, DARK)]),
    ('cap', [('cap', cap, GREEN)]),
]

# --- underfill: extend every mask a few px beneath whatever sits above it ---
flat = [(g, n, m, f) for g, layers in groups for n, m, f in layers]
above = np.zeros_like(dark)
underfilled = []
for gid, name, mask, fill in reversed(flat):
    grown = ndimage.binary_dilation(mask, iterations=4) & above
    underfilled.append((gid, name, mask | grown, fill))
    above |= mask
underfilled.reverse()


def trace(mask, tmpdir, name):
    pbm = os.path.join(tmpdir, name + '.pbm')
    svg = os.path.join(tmpdir, name + '.svg')
    Image.fromarray((~mask * 255).astype(np.uint8)).convert('1').save(pbm)
    subprocess.run(['potrace', '-s', '-t', '12', '-a', '1.0', '-O', '0.2',
                    '-u', '10', pbm, '-o', svg], check=True)
    text = open(svg).read()
    tr = re.search(r'transform="([^"]+)"', text).group(1)
    d = ' '.join(re.findall(r'd="([^"]+)"', text))
    return tr, re.sub(r'\s+', ' ', d).strip()


parts = []
with tempfile.TemporaryDirectory() as tmp:
    for gid, layers in groups:
        parts.append(f'  <g id="{gid}">')
        for name, mask, fill in [(n, m, f) for g, n, m, f in underfilled
                                 if g == gid]:
            tr, d = trace(mask, tmp, name)
            parts.append(f'    <path id="{name}" fill="{fill}" '
                         f'transform="{tr}" d="{d}"/>')
        parts.append('  </g>')

body = '\n'.join(parts)
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
       f'viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n{body}\n</svg>\n')
with open(OUT, 'w') as f:
    f.write(svg)
print('wrote', OUT, len(svg), 'bytes')
