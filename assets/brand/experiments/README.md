# Aberration wordmark library

**Aberration is the product name.** The selected wordmarks are the original
lowercase aligned stack and single line, with separate `t` and `i`. Their
letter outlines, spacing, and exact paired-r mark are preserved.

[Open the current specimen sheet](index.html).

| Layout | Black / inline currentColor | White |
| --- | --- | --- |
| Aligned stack | [stacked-wordmark.svg](stacked-wordmark.svg) | [stacked-wordmark-white.svg](stacked-wordmark-white.svg) |
| Single line | [inline-wordmark.svg](inline-wordmark.svg) | [inline-wordmark-white.svg](inline-wordmark-white.svg) |

Saved previews: [desktop](previews/comparison-desktop.png) and
[mobile](previews/comparison-mobile.png). The capital-A study is excluded from
this current presentation.

## Geometry and use

Each letter is a filled vector outline. The lowercase bodies and the mark are
44 units high, with 10-unit strokes and square corners. The b ascender is
68 units high. The aligned stack has two 218-unit-wide lines; the single-line
ink is 446 by 68 units. Both include 16 units of clear space in the viewBox.

The `letter-rr` path is copied exactly from [the master](../logo.svg), with
translation only. No fonts, bitmaps, external resources, masks, or background
rectangles are used in the wordmark SVGs. Counters and backgrounds are
transparent. Keep the aspect ratio and viewBox when placing them.

The black assets use `currentColor`, defaulting to black as standalone images.
When embedding inline, set `color`; when using an image on a dark background,
choose the explicit white export. The recommended minimum display widths are
160px for the stack and 240px for the single line. Use the standalone mark in
smaller placements.

## Presentation and validation

The specimen sheet uses [specimen.css](specimen.css) for its typography,
spacing, light/dark artboards, responsive layout, and small-size proofs. The
PNG previews render the actual SVG sources in Chrome.

After installing the frontend's locked dependencies, regenerate the previews:

```console
node assets/brand/experiments/render-previews.mjs
```

The renderer checks SVG source consistency, desktop/mobile layouts, image
loading, keyboard focus, and black/white downloads before completing.

The wordmark experiment does not replace the standalone navigation mark. The
existing master and its frontend/documentation exports retain their source
and placement rules in [the brand notes](../README.md).
