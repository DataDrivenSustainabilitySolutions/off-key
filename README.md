<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-white.svg">
    <img src="assets/brand/logo-black.svg" width="64" height="64" alt="Aberration mark">
  </picture>
</p>

<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/wordmark-white.svg">
    <img src="assets/brand/wordmark.svg" width="239" height="50" alt="Aberration">
  </picture>
</h1>

<p align="center">
  Domain-agnostic anomaly detection for connected systems: collect MQTT telemetry,<br>
  run streaming detection pipelines on it and review the evidence.
</p>

<p align="center">
  <a href="https://datadrivensustainabilitysolutions.github.io/off-key/"><strong>Documentation</strong></a> ·
  <a href="https://datadrivensustainabilitysolutions.github.io/off-key/getting-started/">Getting started</a> ·
  <a href="https://datadrivensustainabilitysolutions.github.io/off-key/development/contributing-ci/">Contributing</a>
</p>

## Quick start

Requires Docker with the Compose plugin.

```bash
cp .env.example .env                          # development-only defaults
docker swarm init --advertise-addr 127.0.0.1  # once per Docker engine
docker compose up -d --build
```

The app is then at <http://localhost:5173>. Create the first user and verify the
stack with [Getting started](https://datadrivensustainabilitysolutions.github.io/off-key/getting-started/).
Never deploy with the example credentials; see
[Deployment modes](https://datadrivensustainabilitysolutions.github.io/off-key/operations/deployment-modes/).

## Documentation

| | |
| --- | --- |
| **Use** | [Web app](https://datadrivensustainabilitysolutions.github.io/off-key/user-guide/web-app/) · [Monitoring](https://datadrivensustainabilitysolutions.github.io/off-key/user-guide/monitoring/) |
| **Develop** | [Setup](https://datadrivensustainabilitysolutions.github.io/off-key/development/setup/) · [Architecture](https://datadrivensustainabilitysolutions.github.io/off-key/development/architecture/) · [Testing](https://datadrivensustainabilitysolutions.github.io/off-key/development/testing-debugging/) · [Contributing and CI](https://datadrivensustainabilitysolutions.github.io/off-key/development/contributing-ci/) |
| **Operate** | [Deployment modes](https://datadrivensustainabilitysolutions.github.io/off-key/operations/deployment-modes/) · [Production releases](https://datadrivensustainabilitysolutions.github.io/off-key/operations/production/) · [Recovery](https://datadrivensustainabilitysolutions.github.io/off-key/operations/recovery/) |
| **Reference** | [Environment variables](https://datadrivensustainabilitysolutions.github.io/off-key/reference/environment-variables/) · [Backend API](https://datadrivensustainabilitysolutions.github.io/off-key/reference/backend-api/) · [Brand assets](https://datadrivensustainabilitysolutions.github.io/off-key/reference/brand/) |

The site is built from [`docs/`](docs/index.md); preview it locally with `zensical serve`.

---

<p align="center">
  <a href="https://www.dlr.de/">
    <img src="https://www.dlr.de/de/pt-lf/aktuelles/pressematerial/logos/bmwk/vorschaubild_bmwk_logo-mit-foerderzusatz_en/@@images/image-600-ea91cd9090327104991124b30fe1de7d.png" alt="Funding acknowledgement" width="250">
  </a>
</p>
