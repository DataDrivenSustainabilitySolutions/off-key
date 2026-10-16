# Aberration brand assets

**Aberration is the product name.** The selected lowercase wordmarks integrate
an exact copy of the paired-r mark. The current identity keeps the original
aligned stack and single line, with separate t and i. Aberratio is retained as
an alternative with the merged ti whose lower body matches b.

## Wordmark SVGs

The selected SVGs live here beside the standalone logo and favicon. Each layout
has a black / inline `currentColor` source and an explicit white export.

| Identity and layout | Black / currentColor | White |
| --- | --- | --- |
| Aberration / Single line | [wordmark.svg](wordmark.svg) | [wordmark-white.svg](wordmark-white.svg) |
| Aberration / Aligned stack | [wordmark-stacked.svg](wordmark-stacked.svg) | [wordmark-stacked-white.svg](wordmark-stacked-white.svg) |
| Aberratio / Same-width merged ti | [wordmark-aberratio.svg](wordmark-aberratio.svg) | [wordmark-aberratio-white.svg](wordmark-aberratio-white.svg) |

## Presentation previews

Both specimen sheets share their layout, typography, palette, light/dark
panels, and small-size proofs. Their PNGs render the actual SVG sources.

| Identity | Live specimen | Desktop PNG | Mobile PNG |
| --- | --- | --- | --- |
| Aberration | [aberration.html](previews/aberration.html) | [comparison-desktop.png](previews/comparison-desktop.png) | [comparison-mobile.png](previews/comparison-mobile.png) |
| Aberratio | [aberratio.html](previews/aberratio.html) | [ti-body-desktop.png](previews/ti-body-desktop.png) | [ti-body-mobile.png](previews/ti-body-mobile.png) |

Rejected designs and their comparison pages have been removed from the current
asset set. They remain recoverable in Git history.

After installing the frontend's locked dependencies, regenerate the previews:

```console
node assets/brand/previews/render-previews.mjs
```

The renderer checks SVG sources, desktop/mobile layouts, image loading,
keyboard focus, and black/white downloads. It also measures actual lower-body
ink across b and ti to confirm their matching 44-unit widths.

## Wordmark geometry and use

Each letter is a filled vector outline with square corners and 10-unit strokes.
The lowercase bodies and the paired-r mark are 44 units high. In the current
Aberration lettering, b is 68 units high; the aligned stack has two
218-unit-wide lines, and the single-line ink measures 446 by 68 units. These
wordmarks include 16 units of clear space in their viewBox.

The Aberratio alternative uses a flush t stem with no left crossbar overhang.
Its b and merged ti have 44-unit-wide lower bodies and 6-unit openings.

The `letter-rr` path is copied exactly from [logo.svg](logo.svg), with translation
only. All SVGs use transparent counters and backgrounds with no font dependency.
Preserve their viewBox and aspect ratio. For inline embedding, set `color` on the
black/currentColor source; for an image on a dark background, use the white SVG.
Recommended minimum display widths are 160px for the stack and 240px for either
single-line wordmark. Use the standalone mark in smaller placements.

## Standalone mark and favicon

The master is [logo.svg](logo.svg): the approved paired angular forms, drawn on a
64 × 64 viewBox. It has a transparent background and one editable vector path.
Keep its geometry, proportions, and internal spacing unchanged.

Exports:

- [logo-black.svg](logo-black.svg): black, for light backgrounds.
- [logo-white.svg](logo-white.svg): white, for dark backgrounds.
- [favicon.svg](favicon.svg): transparent, black/white according to the browser's
  colour scheme.

The mark stands alone in application navigation and links to dashboard home.
Give that link an accessible name, “Aberration home”, and a minimum 44 × 44
interaction area. The SVG itself is decorative inside the named link. Render the
mark black on light surfaces and white on dark surfaces; no teal fill, frame,
shadow, perspective, or extra wordmark is needed in the application header.

The master includes 10 units of clear space on every side. Use the full viewBox
and preserve its aspect ratio. A 36px SVG in a 44px button gives the app header a
quiet mark without making its target difficult to activate.

## Updating distributed assets

The frontend, documentation, and self-contained public page have independent
build contexts. Their copies are generated from the master:

    python assets/brand/export.py
    python assets/brand/export.py --check

The export check runs in pre-commit/CI. Edit the master, then regenerate; do not
edit the distributed SVG geometry by hand. The public-page export only replaces
its favicon and logo path, preserving the surrounding layout.

The app references the master's exported path with an external SVG use element,
so its current colour follows the app's explicit light/dark appearance setting.
Documentation embeds the same mark inline and follows its selected theme.
Standalone favicons follow the browser colour scheme through an SVG media query.
