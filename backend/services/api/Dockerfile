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
        postgresql-client \
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

# Install core library
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /code/packages/off-key-core && uv sync --frozen --no-dev --no-install-project

########################################################################################################################
# API Gateway builder
########################################################################################################################
FROM core-installer AS api-builder

# Install API Gateway dependencies
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
# Production API Gateway runtime
########################################################################################################################
FROM python:3.12-slim AS api-gateway

# Optional: add the application virtualenv to search path
ENV PATH=/app/bin:$PATH

# Create non-root user
RUN groupadd -r api && useradd -r -d /app -g api -N api

# Install PostgreSQL client for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built /app directory from api-builder
COPY --from=api-builder --chown=api:api /app /app

USER api
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["sh", "-c", "\
  echo 'Waiting for PostgreSQL to be ready...'; \
  until pg_isready -h postgres -p 5432 -U postgres; do \
    sleep 1; \
  done; \
  echo 'PostgreSQL is available, starting API Gateway...'; \
  uvicorn off_key_api_gateway.main:app --host 0.0.0.0 --port 8000 \
"]