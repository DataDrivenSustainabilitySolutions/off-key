# Production infrastructure

This directory is the authoritative Ansible and Docker Swarm deployment for Aberration.
Application and infrastructure changes share a tested commit. Local development uses
root `docker-compose.yml`; VM provisioning and Windows/network setup are retired.

Start with [GitHub setup](../docs/operations/github-setup.md), then use the
[production runbook](../docs/operations/production.md) and
[recovery runbook](../docs/operations/recovery.md).

```sh
make -C infra setup
make check-infra
# After GitHub setup and a tested main commit:
make deploy-prod REVISION=<full-main-commit-sha>
```

The root deploy command dispatches GitHub Actions. Direct Ansible commands under
`infra/Makefile` remain available for controlled provisioning and recovery.

The public page at `aberration.app` is the self-contained
[`stack/landing.html.j2`](stack/landing.html.j2) template, served separately from
the dashboard. The landing page leads with a photographic industrial sensor
assembly on a light studio background, followed by dark technical sections.
Its generated concept image is embedded from `landing-hero.b64.j2`; the source
asset and generation prompt live in `../assets/landing/`. Regenerate the embedded
image with `python3 assets/landing/export.py` after updating the selected JPEG.
Keep rendered HTML below the 500 KB Swarm config limit. The page needs no
scripts, external assets, or backend access, and respects reduced-motion settings.
Dashboard links use the configured `frontend_base_url`; legacy account/API
forwarding remains in Traefik.
The monochrome mark and favicon come from [`../assets/brand/`](../assets/brand/);
run `python assets/brand/export.py` from the repository root after editing the
master SVG. The export preserves the page's surrounding design.

The header's For agents link and footer's Humans / Agents links show an `#agents`
view for people handing Aberration to their own agent. Behind it, the same nginx service serves
[`landing-llms.txt.j2`](stack/landing-llms.txt.j2) at `/llms.txt` (the
[llmstxt.org](https://llmstxt.org/) index) and
[`landing.md.j2`](stack/landing.md.j2) at `/index.md`, which `/` also returns
for `Accept: text/markdown` ([`landing-nginx.conf`](stack/landing-nginx.conf)).
Keep the Markdown in step with the page copy. The documentation build publishes
the matching `llms.txt`, `llms-full.txt` and per-page Markdown at
`https://docs.aberration.app` (`dev/docs/llms.py`). The docs image is built,
verified and deployed with the production release; see
[documentation hosting](../docs/operations/production.md#documentation-hosting).

The footer opens self-contained Impressum, Privacy, and Contact sections using
fragment links. Their bracketed fields are intentional templates; replace them
with verified operator, privacy, and contact information before publication.
The sections and close links work without JavaScript or additional routes.

Never commit inventories, vaults, passwords, credentials, tailnet identity or backups.
The original private infrastructure repository remains the historical archive until
an operator verifies the first integrated release and archives it.
