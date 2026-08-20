#!/usr/bin/env python3
"""verify.py — prove a traced SVG matches its source PNG.

Renders the SVG with resvg at the source's pixel size, composites both over
white, and reports per-pixel differences. Optionally writes a diff heatmap.

Requires: pillow, numpy (pip) and resvg (e.g. `brew install resvg`).
"""
import argparse
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image


def over_white(a):
    al = a[..., 3:4] / 255.0
    return a[..., :3] * al + 255.0 * (1 - al)


def main():
    ap = argparse.ArgumentParser(description='Pixel-diff a traced SVG '
                                             'against its source PNG.')
    ap.add_argument('png', help='original raster image')
    ap.add_argument('svg', help='traced SVG to check')
    ap.add_argument('--diff-out', help='write a diff heatmap PNG here')
    ap.add_argument('--fail-mean', type=float, default=None,
                    help='exit nonzero if mean abs diff exceeds this')
    args = ap.parse_args()

    orig = np.array(Image.open(args.png).convert('RGBA')).astype(float)
    h, w = orig.shape[:2]
    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        subprocess.run(['resvg', '--width', str(w), '--height', str(h),
                        args.svg, tmp.name], check=True)
        new = np.array(Image.open(tmp.name).convert('RGBA')).astype(float)

    diff = np.abs(over_white(orig) - over_white(new)).max(-1)
    mean = diff.mean()
    big = (diff > 64).mean() * 100
    print(f'mean abs diff: {mean:.2f}/255   '
          f'pixels off by >64: {big:.2f}%   max: {diff.max():.0f}')

    if args.diff_out:
        Image.fromarray(np.clip(diff, 0, 255).astype('uint8')).save(
            args.diff_out)
        print(f'diff heatmap -> {args.diff_out}')

    if args.fail_mean is not None and mean > args.fail_mean:
        sys.exit(f'FAIL: mean {mean:.2f} > {args.fail_mean}')


if __name__ == '__main__':
    main()
