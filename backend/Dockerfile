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
# Base builder stage - common dependencies and setup
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
# API application builder
########################################################################################################################
FROM base-builder AS api-builder

# Install API dependencies (no MQTT extras)
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
# MQTT service builder
########################################################################################################################
FROM base-builder AS mqtt-builder

# Install MQTT dependencies (includes MQTT extras)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project \
        --extra mqtt

# Copy source code
COPY . /code

# Install project itself with MQTT extras
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable \
        --extra mqtt

########################################################################################################################
# Worker service builder
########################################################################################################################
FROM base-builder AS worker-builder

# Install worker dependencies (includes all extras for flexibility)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project \
        --extra mqtt

# Copy source code
COPY . /code

# Install project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-editable \
        --extra mqtt

########################################################################################################################
# Production API runtime
########################################################################################################################
FROM python:3.12-slim AS api

# Optional: add the application virtualenv to search path
ENV PATH=/app/bin:$PATH

# Create non-root user
RUN groupadd -r app && useradd -r -d /app -g app -N app

# Install PostgreSQL client for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built /app directory from api-builder
COPY --from=api-builder --chown=app:app /app /app

USER app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["sh", "-c", "\
  echo 'Waiting for PostgreSQL to be ready...'; \
  until pg_isready -h postgres -p 5432 -U postgres; do \
    sleep 1; \
  done; \
  echo 'PostgreSQL is available, running admin creation script...'; \
  /app/bin/python -c 'import off_key.scripts.create_admin' || echo 'Import failed'; \
  /app/bin/python -m off_key.scripts.create_admin || echo 'Admin might already exist.'; \
  echo 'Starting FastAPI server...'; \
  uvicorn off_key.main:app --host 0.0.0.0 --port 8000 \
"]

########################################################################################################################
# Production MQTT runtime
########################################################################################################################
FROM python:3.12-slim AS mqtt

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
CMD ["/app/bin/python", "-m", "off_key.services.mqtt.proxy_service"]

########################################################################################################################
# Production worker runtime
########################################################################################################################
FROM python:3.12-slim AS worker

# Optional: add the application virtualenv to search path
ENV PATH=/app/bin:$PATH

# Create non-root user
RUN groupadd -r worker && useradd -r -d /app -g worker -N worker

# Copy the pre-built /app directory from worker-builder
COPY --from=worker-builder --chown=worker:worker /app /app

USER worker
WORKDIR /app

# Default command - can be overridden
CMD ["/app/bin/python", "-m", "off_key.services.resources.proxy"]
