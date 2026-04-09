FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

LABEL org.opencontainers.image.source="https://github.com/DataDrivenSustainabilitySolutions/off-key" \
      org.opencontainers.image.description="Development container image for the Off-Key predictive maintenance platform" \
      org.opencontainers.image.licenses="MIT"

RUN find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) -exec sed -i "/dl\\.yarnpkg\\.com/s/^/# disabled invalid yarn repo: /" {} + \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        make \
        pkg-config \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv and uvx from the official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
