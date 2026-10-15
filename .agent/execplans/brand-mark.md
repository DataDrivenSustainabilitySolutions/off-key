# Integrate the Aberration mark

## Objective

Use the selected middle study as Aberration's vector mark throughout the
application, browser favicon, documentation, and public website. The app mark
links to the unfiltered dashboard home at /. Render black on light surfaces and
white on dark surfaces, including explicit appearance settings.

.agent/PLANS.md is absent; this file records the execution plan directly.
Limit public-page changes to branding, preserving its layout and deployment.

## Approach

- Keep the approved geometry in assets/brand/logo.svg. Export plain black/white
  versions and adaptive favicons into the separate application/docs build roots.
- Use one accessible home-link component in shared navigation, authentication,
  and error pages. Keep the mark decorative inside the named link.
- Update existing public-page branding without adding external requests or
  changing its deployment and CSP contracts.
- Document the master assets, exports, sizing, and intended colour treatment.

## Progress

- [x] Inspect existing branding, navigation, themes, build contexts, and local edits.
- [x] Integrate the mark and deterministic asset exports.
- [x] Validate application navigation and themes against the real local stack.
- [x] Build documentation and inspect its mark in both colour schemes.
- [x] Verify the public template.
- [x] Run affected lint, test, build, and asset consistency checks.

## Validation

Run the frontend lint, tests, and production build. Exercise the actual compiled
frontend with the existing real backend and authentication: the mark must return
from Sources/Reporting/account pages to dashboard home without a full document
reload, and invert when appearance changes. Verify auth/error branding and the
favicon in light/dark browser rendering. Build the documentation strictly, render
the actual public Jinja template with its production CSP, and inspect desktop
and narrow layouts. Check exported assets against the vector master.

## Results

The selected geometry is unchanged. The shared application header, authentication
pages, and route errors use one named home link and the exported SVG path. The
public page, README, documentation header/reference, and favicons use the same
master. Documentation embeds the mark inline so an operating-system preference
cannot make it disappear against an explicitly selected opposite theme.

All 603 frontend tests pass across 52 files. Password-recovery tests now mount
the router required by the home link. The existing deep-link test waits for its
asynchronous catalogue-scope restoration before selecting the topic. Frontend
lint, production build, final TypeScript check, strict Zensical build, Ruff, asset
consistency, and whitespace checks pass.

The new committed browser journey passes against the real compiled Docker
frontend and its existing authenticated backend: keyboard activation of the logo
returns from Sources, Reporting, and Account without a full document reload;
the mark follows explicit light/dark settings and has a 44px target.

Additional real Chrome validation passes for the application at 320, 390, and
1280px in both themes; standalone favicon paint in both browser schemes;
authentication/error home links; documentation automatic and explicit palettes;
and the actual Jinja public template at 320/1280px under its production CSP with
JavaScript disabled. There is no horizontal overflow, failed logo load, page
error, or public-page CSP error. Screenshots were visually inspected and remain
in ignored .tmp/brand-preview/images, separate from the existing UI gallery.
