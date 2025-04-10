# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim-bookworm AS builder

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv
# TODO (SECURITY): Attest origin
COPY --from=uv /uv /uvx /bin/

# - Silence uv complaining about not being able to use hard links,
# - Tell uv to byte-compile packages for faster application startups,
# - Prevent uv from accidentally downloading isolated Python builds,
# - Pick a Python (use `/usr/bin/python3.12` on uv 0.5.0 and later),
# - Declare `/app` as the target for `uv sync`.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/app

# Set project path
WORKDIR /code

# Synchronize DEPENDENCIES without the application itself.
# This layer is cached until uv.lock or pyproject.toml change, which are
# only temporarily mounted into the build container since we don't need
# them in the production one.
# Inside off-key/backend/Dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project

# Copy source code (will NOT be copied into the runtime container)
COPY . /code

# Install project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable

########################################################################################################################
FROM python:3.12-slim

# Optional: add the application virtualenv to search path.
ENV PATH=/app/bin:$PATH

# Create non-root user
RUN <<EOT
groupadd -r app
useradd -r -d /app -g app -N app
EOT

# Copy the pre-built `/app` directory to the runtime container
# Change the ownership to user app and group app in one step.
COPY --from=builder --chown=app:app /app /app

USER app

WORKDIR /app

# Expose port
EXPOSE 8000

# Command to run the application
# TODO: Expose proper entrypoint
CMD ["uvicorn", "off_key.main:app", "--host", "0.0.0.0", "--port", "8000"]
