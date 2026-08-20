# logo2svg

Deterministically trace a flat-color PNG (logo, icon, illustration) into a
**layered, animation-ready SVG** — an exact visual copy, not a redraw.

Same PNG in → byte-identical SVG out, every time. No AI in the conversion
loop, no randomness: just pixel classification, connected-component analysis,
and [potrace](https://potrace.sourceforge.net/)'s deterministic curve fitting.

## Why: AI-designed logos → animatable SVGs

Image models are now very good at designing logos — but they hand you a
raster PNG. The moment you want the logo to *move* (an intro animation, a
hover effect, elements sliding apart), you need an SVG with each element as
its own addressable path. Redrawing by hand loses the original's exact look;
naive auto-tracers give you one tangled path.

`logo2svg` bridges that gap: it reproduces the AI's artwork exactly (verified
by pixel diff) while splitting it into separate stacked shapes you can target
with CSS/JS animation. The workflow that produced this repo:

1. An image model designed a logo (a phone with a sofa flying out of it).
2. `logo2svg` traced it into layered vector paths — mean pixel difference
   3/255 against the original, differing only in edge anti-aliasing.
3. A quick semantic pass named the layers (`#phone`, `#couch`, `#speed-lines`,
   `#figure`, `#cap`), ready for animation. See
   [`examples/snapcycle/`](examples/snapcycle/).

## Install

```sh
brew install potrace        # the curve tracer (apt: potrace)
pip install pillow numpy scipy
brew install resvg          # optional, only needed by verify.py
```

## Usage

```sh
python3 logo2svg.py logo.png -o logo.svg
python3 verify.py logo.png logo.svg --diff-out diff.png   # prove fidelity
```

Output structure — one group per detected color (bottom layer first), one
path per shape:

```xml
<svg viewBox="0 0 671 600">
  <g id="layer0" data-color="#e2ece6">
    <path id="layer0-shape0" .../>
    ...
  </g>
  <g id="layer1" data-color="#15211c">...</g>
  ...
</svg>
```

Useful flags (all deterministic):

| flag | default | what it does |
|---|---|---|
| `--max-colors` | 8 | palette size ceiling before filtering |
| `--min-share` | 0.005 | drop colors covering < this share of pixels |
| `--merge-dist` | 32 | merge palette colors closer than this RGB distance |
| `--min-size` | 40 | drop shapes smaller than this (anti-aliasing debris) |
| `--underfill` | 4 | px each shape extends beneath upper layers (no seams) |
| `--alpha-threshold` | 128 | alpha at/above which a pixel counts as opaque |

## How it works

1. **Palette detection** — median-cut quantization (no dither) finds the
   dominant flat colors; near-duplicates merge, rare colors drop.
2. **Classification** — every opaque pixel is assigned to its nearest
   palette color; fills use the true mean color of each class.
3. **Segmentation** — each color class splits into connected components:
   the individual shapes.
4. **Underfill** — each shape is dilated a few pixels *only where a
   later-drawn shape covers it*, so the stacked result has no hairline seams
   and upper layers can be moved without gaps appearing at their old edges.
5. **Tracing** — potrace converts each shape's bitmap mask into smooth
   bezier paths.
6. **Assembly** — shapes are stacked largest-color-first into one SVG with
   ids on every group and path.

## Semantic naming (the optional 20%)

The CLI emits anonymous `layer0-shape3` ids — correct, but not meaningful.
For animation you usually want `#cap` and `#speed-line-2`. That mapping is
knowledge about the *specific image* ("the largest green blob is the couch"),
so it can't be fully generic. Two ways to get it:

- **A short bespoke script** that picks components by size/position and
  stacks them in occlusion order —
  [`examples/snapcycle/semantic_trace.py`](examples/snapcycle/semantic_trace.py)
  is a complete worked example (~100 lines, mostly reusable boilerplate).
- **An LLM pass**: give a coding agent the CLI's output and the source image
  and ask it to rename/regroup the paths. Naming ~15 shapes is a task
  agents handle reliably; the pixel-exact tracing stays deterministic.

## Limits

- **Flat-color art only.** Photos and gradients vectorize into thousands of
  noisy paths — keep those raster.
- Shapes smaller than `--min-size` px are dropped (usually anti-aliasing
  debris; lower the threshold if your art has real tiny details).
- The SVG reproduces the *visible* pixels. Parts of a shape hidden behind
  another shape in the source stay missing until you patch them by hand —
  the underfill only covers a few pixels of overlap, enough for seams, not
  for full reveals.

## License

MIT
