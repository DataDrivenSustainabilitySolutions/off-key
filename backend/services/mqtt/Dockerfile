# syntax=docker/dockerfile:1

########################################################################################################################
# Lock file generation stage
########################################################################################################################
FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim-bookworm AS lock-generator

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=uv /uv /uvx /bin/

# Configure uv environment
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

# Set project path
WORKDIR /code

# Copy project files
COPY pyproject.toml ./

# Generate lock file
RUN uv lock

########################################################################################################################
# Base builder stage
########################################################################################################################
FROM python:3.12-slim-bookworm AS base-builder

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=uv /uv /uvx /bin/

# Configure uv environment
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/app

# Set project path
WORKDIR /code

# Copy project files and generated lock file
COPY pyproject.toml ./
COPY --from=lock-generator /code/uv.lock ./

########################################################################################################################
# Install shared core library
########################################################################################################################
FROM base-builder AS core-installer

# Copy core library
COPY ../../packages/core /code/packages/off-key-core

# Install core library with MQTT extras
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /code/packages/off-key-core && uv sync --frozen --no-dev --no-install-project --extra mqtt

########################################################################################################################
# MQTT Proxy builder
########################################################################################################################
FROM core-installer AS mqtt-builder

# Install MQTT Proxy dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project

# Copy source code
COPY . /code

# Install project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable

########################################################################################################################
# Production MQTT Proxy runtime
########################################################################################################################
FROM python:3.12-slim AS mqtt-proxy

# Optional: add the application virtualenv to search path
ENV PATH=/app/bin:$PATH

# Create non-root user
RUN groupadd -r mqtt && useradd -r -d /app -g mqtt -N mqtt

# Install system dependencies for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built /app directory from mqtt-builder
COPY --from=mqtt-builder --chown=mqtt:mqtt /app /app

USER mqtt
WORKDIR /app

# Run the MQTT proxy service
CMD ["/app/bin/python", "-m", "off_key_mqtt_proxy"]