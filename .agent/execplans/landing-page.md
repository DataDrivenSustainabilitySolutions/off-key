# Bring the public landing page into the application design

## Goal and context

Rework the independent public landing page in `infra/stack/landing.html.j2`
to feel like the application. Preserve the configured dashboard destination and
the existing ingress redirects. The application uses system sans-serif text,
slate neutrals, teal primary colours, subtle borders, and an 8px base radius.
It follows the system colour scheme by default. The public page currently uses
black and white, Courier throughout, and sharp borders.

The page is a self-contained nginx Swarm config. Its production CSP permits
inline CSS and data images but no JavaScript, fonts, or external requests.
Keep that deployment contract. No new runtime configuration is needed.
`.agent/PLANS.md` is absent; this file records the execution plan directly.

## Design

- Match the application font stack, light/dark colour tokens, radii, wordmark,
  button treatment, and restrained visual hierarchy.
- Use a spacious hero and an accessible abstract contour illustration with a
  teal departure from a shared pattern. Explain the observe/calibrate/detect flow.
- Follow the system colour scheme with CSS. Keep the page entirely static and
  independent from application assets, authentication, and backend services.
- Preserve escaped Jinja variables for the canonical URL and dashboard links.
- Retain keyboard focus, skip navigation, meaningful headings, and usable
  layouts from 320px through wide desktop viewports.

## Progress

- [x] Inspect the application, public template, ingress, and existing validation.
- [x] Rebuild the landing layout and document its design/deployment contract.
- [x] Render the real Jinja template and verify it with production CSP headers.
- [x] Inspect desktop/mobile and light/dark output; exercise dashboard links.
- [x] Check the final diff and record verification results.
- [x] Verify the abstract illustration in both themes and mobile layouts.
- [x] Create `codex/landing-page-refresh` from the current `origin/main`.
- [x] Commit, push, and create the landing-page pull request.

## Validation

Render the template using Jinja with strict undefined variables and the actual
production domain/destination. Serve it locally with the production landing CSP.
Use real browser rendering to inspect responsive layouts, colour schemes,
keyboard focus, in-page navigation, and dashboard navigation. Check that the
template remains self-contained, parses correctly, and escapes URL values.
Run affected infrastructure routing/rendering checks where the host supports
their Ansible/Docker runtime. No application or backend source changes are
planned, so their unrelated suites are outside this task.

## Results and refinements

The landing page now uses the application font stack, exact light/dark palette
values, teal controls, a slash monogram, restrained borders and rounded surfaces.
The abstract illustration uses nested organic contours and a teal contour that
departs from the shared pattern. It conveys change without axes, detector
thresholds, or a simulated application panel. An accessible title/description
and an HTML caption accompany the self-contained SVG. The three-step workflow
explains detection, and the page stays entirely static under its existing CSP.

The real Jinja environment with strict undefined variables renders successfully
against production inventory values. Checks confirm URL escaping, three correct
dashboard links, no external asset dependencies or active content, exact palette
parity, and the rendered production landing/dashboard routes and legacy redirect
including preservation of query strings. No routing files were modified.

Chrome validation passes at 320, 390, 760, 768, 1024 and 1440px in both light and
dark themes. There is no horizontal overflow or clipped content at those widths.
Keyboard focus, skip navigation, section navigation, all dashboard links, and
live system-theme changes work with JavaScript disabled. A separately rendered
copy points the dashboard configuration at the real local application on port
5174; all links navigate there, and a normal browser follows through to the real
React login page. The production destination is checked independently in the
unaltered production render. No mocked routes or responses were used.

The final contour illustration was re-rendered and the same twelve browser
combinations and real application handoff passed again. The SVG has a separate
accessible name and description, and it uses internal path references under the
existing production CSP. Desktop light/dark, narrow mobile and forced-colours
screenshots were inspected after the change.

Desktop, 320px and 390px screenshots in both themes and a forced-colours mobile
view were inspected. They are in the chat visualization directory, named
`landing-light.png`, `landing-dark.png`, `landing-light-390.png` and corresponding
variants. `git diff --check` passes. Temporary validation scripts and output live
under `.tmp/landing-preview/`; the preview is at `http://127.0.0.1:4176/`.
The implementation is published for review in
[PR #302](https://github.com/DataDrivenSustainabilitySolutions/off-key/pull/302)
from `codex/landing-page-refresh`, based directly on `main`. Publication uses the
isolated managed `landing-page-refresh` worktree. Production has not been deployed.

## Follow-up: simplify the hero and add a useful footer (2026-10-16)

Remove the visible anomaly-detection eyebrow, the streaming-data strapline, and
the abstract hero SVG. Centre the remaining introduction and actions so there
is no empty illustration column. Preserve the current exported brand mark and
all configured dashboard links.

Replace the marketing footer with Impressum, Privacy, and Contact navigation.
Each fragment link reveals an accessible in-page section and a close link
returns to the footer. The sections contain clearly identified bracketed
templates for real operator and policy details, without invented identities or
claims about data handling. Keep the page independent and JavaScript-free.

- [x] Rework the hero and add footer navigation and template sections.
- [x] Verify responsive layout, keyboard operation, direct fragment navigation,
      closing, light/dark/forced-colour output, and dashboard forwarding.
- [x] Review screenshots and the final scoped diff.

Validation passed at 320, 390, 760, 768, 1024 and 1440px in both light and dark
themes, including all three legal sections, native keyboard focus/closing,
direct fragment reloads and browser back/forward navigation. All four dashboard
links navigate to the real local application, and a normal browser reaches its
React login page. The page works with JavaScript disabled under the production
CSP. No routes or backend services changed. The brand-export consistency check
and `git diff --check` pass. Desktop/mobile and forced-colour screenshots were
visually reviewed. Changes are on the local `codex/landing-page-footer` branch
in the existing isolated landing-page worktree. The requested production release
uses the repository's required pull-request checks, tested main commit, and
verified production deployment workflow.
