# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.14-slim-bookworm AS builder

# Build context MUST be backend/

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=uv /uv /uvx /bin/

# - Silence uv complaining about not being able to use hard links,
# - Tell uv to byte-compile packages for faster application startups,
# - Prevent uv from accidentally downloading isolated Python builds,
# - Use the Python interpreter supplied by the base image,
# - Declare `/app` as the target for `uv sync`.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python \
    UV_PROJECT_ENVIRONMENT=/app

# Set project path
WORKDIR /code

# Set project-specific variables
ARG SERVICE_NAME
ARG SERVICE_ROOT

# Synchronize DEPENDENCIES without the application itself.
# This layer is cached until uv.lock or pyproject.toml change, which are
# only temporarily mounted into the build container since we don't need
# them in the production one.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=${SERVICE_ROOT}/pyproject.toml,target=${SERVICE_ROOT}/pyproject.toml \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-workspace \
        --package ${SERVICE_NAME}

# Copy source code (will NOT be copied into the runtime container)
COPY pyproject.toml uv.lock /code/
COPY libs/ /code/libs/
COPY ${SERVICE_ROOT} /code/${SERVICE_ROOT}

# Install project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable \
        --package ${SERVICE_NAME}

# Leave out what no service runs; only /app reaches the runtime image.
# - The packages' own test suites (directories named "tests"), which nothing imports.
# - For RADAR, matplotlib and the packages that only it needs, as uv.lock resolves them.
#   PyOD declares matplotlib for its plotting helpers and for detectors RADAR does not
#   offer (aberration_core.models.static).
RUN find /app/lib -depth -type d -name tests -path '*/site-packages/*' -exec rm -rf {} + \
    && if [ "$SERVICE_NAME" = "aberration-mqtt-radar" ]; then \
        export_args="--frozen --no-dev --package $SERVICE_NAME --no-emit-workspace --no-header --no-hashes --no-annotate" \
        && uv export $export_args > /tmp/locked.txt \
        && uv export $export_args --prune matplotlib > /tmp/kept.txt \
        && uv pip uninstall --python /app/bin/python $(grep -vxFf /tmp/kept.txt /tmp/locked.txt | cut -d= -f1); \
    fi

# Verify the shipped metadata against the actual RADAR dependency environment, then
# import every RADAR module and offered component from it, so a change that needs a
# package the image leaves out fails this build instead of a running monitor.
RUN --mount=type=bind,source=scripts/check_radar_image.py,target=/tmp/check_radar_image.py \
    if [ "$SERVICE_NAME" = "aberration-mqtt-radar" ]; then \
        /app/bin/python -m aberration_mqtt_radar.catalog --check \
        && /app/bin/python /tmp/check_radar_image.py; \
    fi

# Partition the already-verified venv, preserving every installed runtime file.
# Source edits then replace only workspace packages in the final image; the much
# larger third-party dependency layer keeps its digest and stays on each node.
RUN --mount=type=bind,source=scripts/split_runtime_layers.py,target=/tmp/split_runtime_layers.py \
    python /tmp/split_runtime_layers.py /app /code /application

########################################################################################################################
FROM python:3.14-slim-bookworm

# Optional: add the application virtualenv to search path.
ENV PATH=/app/bin:$PATH

# User creation is independent of release labels, so it stays cached across commits.
RUN <<EOT
groupadd -r app
useradd -r -d /app -g app -N app
EOT

ARG SERVICE_NAME
ARG IMAGE_VERSION=dev
ARG GIT_COMMIT=unknown

LABEL org.opencontainers.image.source="https://github.com/DataDrivenSustainabilitySolutions/aberration" \
      org.opencontainers.image.title="${SERVICE_NAME}" \
      org.opencontainers.image.description="Runtime image for the ${SERVICE_NAME} service in the Aberration platform" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

# Copy the pre-built `/app` directory to the runtime container
# Change the ownership to user app and group app in one step.
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /application /app

USER app

WORKDIR /app
