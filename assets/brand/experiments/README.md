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
this current presentation; its SVG remains in the retained studies.

## Retained alternative: Aberratio

The [matching specimen sheet](ti-body.html) preserves the **merged-ti** design
as an alternative. This is a retained experiment; the product name remains
**Aberration**. The current Aberration wordmarks above keep their separate t/i.

| Aberratio study | Black / inline currentColor | White |
| --- | --- | --- |
| Body-matched merged ti | [aberratio-flush-ti.svg](aberratio-flush-ti.svg) | [aberratio-flush-ti-white.svg](aberratio-flush-ti-white.svg) |
| Earlier merged compound | [aberratio-open.svg](aberratio-open.svg) | [aberratio-open-white.svg](aberratio-open-white.svg) |

Saved previews: [desktop](previews/ti-body-desktop.png) and
[mobile](previews/ti-body-mobile.png). Both pages use the same specimen layout,
typography, palette, light/dark panels, and small-size proofs.

The flush t stem removes the short left crossbar overhang. The lower bodies of
b and ti each span 44 units, with 10-unit strokes and 6-unit openings. The earlier
compound spans 44 units overall but only 34 below its crossbar; it is preserved
for comparison. Only ti changes between these two wordmarks. The mark sits at
the centre of the seven-cell Aberratio composition.

## Earlier studies

All existing SVG variants are retained, including the capital-A study removed
from the current comparison. These are historical alternatives, not the current
product selection:

| Study | Black | White |
| --- | --- | --- |
| Offset stack, capital A | [SVG](stacked-wordmark-offset.svg) | [SVG](stacked-wordmark-offset-white.svg) |
| Aberration, closer spacing | [SVG](inline-wordmark-tight.svg) | [SVG](inline-wordmark-tight-white.svg) |
| Aberration, shorter ascenders | [SVG](inline-wordmark-short-ascenders.svg) | [SVG](inline-wordmark-short-ascenders-white.svg) |
| Aberratio, paired closed b | [SVG](aberratio-paired.svg) | [SVG](aberratio-paired-white.svg) |
| Aberration, earlier paired ti | [SVG](aberration-paired.svg) | [SVG](aberration-paired-white.svg) |

The [spacing comparison](refinements.html) and [paired-letter comparison](pairing.html)
retain their original study layouts. New design iterations should be saved
separately so that both selected families remain intact.

## Current Aberration geometry and use

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
loading, keyboard focus, and black/white downloads before completing. It also
measures actual lower-body ink across b and ti, rather than relying on the
crossbar's outer bounds.

The wordmark experiment does not replace the standalone navigation mark. The
existing master and its frontend/documentation exports retain their source
and placement rules in [the brand notes](../README.md).
