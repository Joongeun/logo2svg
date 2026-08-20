#!/usr/bin/env python3
"""logo2svg — deterministic flat-color PNG -> layered, animation-ready SVG.

Pipeline:
  1. Detect the image's flat-color palette (median-cut quantize, no dither).
  2. Classify every opaque pixel to its nearest palette color.
  3. Split each color class into connected components (the individual shapes).
  4. Extend each shape a few pixels *underneath* whatever is drawn above it,
     so stacked layers never show hairline seams.
  5. Trace every shape with potrace into smooth bezier paths.
  6. Assemble one SVG with a named <g> per color layer, one <path> per shape.

Every step is deterministic: the same PNG always produces the same SVG.

Requires: pillow, numpy, scipy (pip) and potrace (e.g. `brew install potrace`).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage


def detect_palette(rgb, opaque, max_colors, min_share, merge_dist):
    """Return the dominant flat colors as an (N, 3) array, biggest class first."""
    pixels = rgb[opaque].reshape(-1, 1, 3).astype('uint8')
    q = Image.fromarray(pixels).quantize(
        colors=max_colors, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette()).reshape(-1, 3)[:max_colors]
    counts = np.bincount(np.array(q).ravel(), minlength=len(pal))
    total = counts.sum()
    kept = []
    for i in np.argsort(-counts):
        if counts[i] / total < min_share:
            continue
        if any(np.linalg.norm(pal[i] - pal[j]) < merge_dist for j in kept):
            continue
        kept.append(i)
    return pal[kept]


def classify(rgb, opaque, palette):
    """Assign each opaque pixel to its nearest palette color; refine the
    palette to the true mean of each class (better fill fidelity)."""
    dists = np.stack(
        [((rgb.astype(int) - c) ** 2).sum(-1) for c in palette], -1)
    cls = np.argmin(dists, -1)
    refined = np.array([
        rgb[opaque & (cls == i)].mean(0) if (opaque & (cls == i)).any() else c
        for i, c in enumerate(palette)])
    return cls, refined.round().astype(int)


def components(mask, min_size):
    """Connected components of a boolean mask, largest first."""
    lab, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    order = np.argsort(-sizes)
    return [lab == i + 1 for i in order if sizes[i] >= min_size]


def trace(mask, tmpdir, name):
    """Run potrace on a boolean mask; return (transform, path data)."""
    pbm = os.path.join(tmpdir, name + '.pbm')
    svg = os.path.join(tmpdir, name + '.svg')
    Image.fromarray((~mask * 255).astype(np.uint8)).convert('1').save(pbm)
    subprocess.run(['potrace', '-s', '-t', '12', '-a', '1.0', '-O', '0.2',
                    '-u', '10', pbm, '-o', svg], check=True)
    text = open(svg).read()
    transform = re.search(r'transform="([^"]+)"', text).group(1)
    d = ' '.join(re.findall(r'd="([^"]+)"', text))
    return transform, re.sub(r'\s+', ' ', d).strip()


def main():
    ap = argparse.ArgumentParser(
        description='Deterministically trace a flat-color PNG (logo, icon, '
                    'illustration) into a layered SVG ready for animation.')
    ap.add_argument('input', help='source PNG (flat colors, e.g. a logo)')
    ap.add_argument('-o', '--output', help='output SVG (default: input .svg)')
    ap.add_argument('--max-colors', type=int, default=8,
                    help='palette size ceiling before filtering (default 8)')
    ap.add_argument('--min-share', type=float, default=0.005,
                    help='drop palette colors covering less than this share '
                         'of opaque pixels (default 0.005)')
    ap.add_argument('--merge-dist', type=float, default=32,
                    help='merge palette colors closer than this RGB distance '
                         '(default 32)')
    ap.add_argument('--min-size', type=int, default=40,
                    help='drop shapes smaller than this many pixels — filters '
                         'anti-aliasing debris (default 40)')
    ap.add_argument('--underfill', type=int, default=4,
                    help='pixels each shape extends beneath upper layers to '
                         'prevent seams (default 4)')
    ap.add_argument('--alpha-threshold', type=int, default=128,
                    help='alpha value at or above which a pixel counts as '
                         'opaque (default 128)')
    ap.add_argument('--smooth', type=int, default=1,
                    help='px of morphological close+open per shape, smooths '
                         'jagged anti-aliased edges (default 1, 0 disables)')
    args = ap.parse_args()
    out = args.output or os.path.splitext(args.input)[0] + '.svg'

    im = Image.open(args.input).convert('RGBA')
    a = np.array(im)
    H, W = a.shape[:2]
    rgb, alpha = a[..., :3], a[..., 3]
    opaque = alpha >= args.alpha_threshold
    if not opaque.any():
        sys.exit('error: image has no opaque pixels')

    palette = detect_palette(rgb, opaque, args.max_colors,
                             args.min_share, args.merge_dist)
    cls, palette = classify(rgb, opaque, palette)
    hexes = ['#%02x%02x%02x' % tuple(c) for c in palette]
    print(f'{args.input}: {W}x{H}, palette ' + ', '.join(hexes))

    # flat draw list: color layers biggest-first (bottom), shapes within each
    flat = []
    for li, hx in enumerate(hexes):
        shapes = components(opaque & (cls == li), args.min_size)
        for ci, m in enumerate(shapes):
            if args.smooth:
                m = ndimage.binary_opening(
                    ndimage.binary_closing(m, iterations=args.smooth),
                    iterations=args.smooth)
                if not m.any():
                    continue
            flat.append((li, f'layer{li}-shape{ci}', m, hx))
        print(f'  layer {li} ({hx}): {len(shapes)} shape(s)')

    # underfill: extend every shape beneath the union of later-drawn shapes
    above = np.zeros((H, W), bool)
    underfilled = []
    for li, name, mask, hx in reversed(flat):
        if args.underfill:
            mask = mask | (ndimage.binary_dilation(
                mask, iterations=args.underfill) & above)
        underfilled.append((li, name, mask, hx))
        above |= mask
    underfilled.reverse()

    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        current = None
        for li, name, mask, hx in underfilled:
            if li != current:
                if current is not None:
                    parts.append('  </g>')
                parts.append(f'  <g id="layer{li}" data-color="{hx}">')
                current = li
            transform, d = trace(mask, tmp, name)
            parts.append(f'    <path id="{name}" fill="{hx}" '
                         f'transform="{transform}" d="{d}"/>')
        if current is not None:
            parts.append('  </g>')

    body = '\n'.join(parts)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n{body}\n</svg>\n')
    with open(out, 'w') as f:
        f.write(svg)
    print(f'wrote {out} ({len(svg)} bytes, {len(flat)} paths)')


if __name__ == '__main__':
    main()
