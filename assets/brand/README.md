# Aberration brand assets

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
