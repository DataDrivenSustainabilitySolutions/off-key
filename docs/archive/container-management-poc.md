!!! warning "Archived page"
    This page is retained for historical reference and may not match the present implementation.

    Maintained guidance:

    - [Architecture](../development/architecture.md)
    - [Backend API](../reference/backend-api.md)
    - [Archive index](index.md)

---
## Summary

This PoC extends our current FastAPI implementation with asynchronous container lifecycle management capabilities.


## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │────│  Docker Daemon  │────│   Containers    │
│  + Rate Limiter │    │                 │    │                 │
│   (SlowAPI)     │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │
         │
┌─────────────────┐
│   Database      │
│   (SQLAlchemy)  │
└─────────────────┘
```
**Description**
- **FastAPI Application**: Web framework serving as the API layer
- **Docker Integration**: Direct communication with Docker daemon via `docker-py` library
- **Database Layer**: SQLAlchemy-based async persistence for container metadata
- **Container Layer**: Docker containers running monitoring services that subscribe to and process MQTT topics in real-time (🚧 **WIP**)

## Current Implementation Details

### Asynchronous Docker Operations

To prevent blocking the main event loop, all Docker daemon interactions are wrapped using `asyncio.to_thread()` (or similar async wrapper).
This approach ensures that:

- ✅ Docker API calls don't block the FastAPI event loop
- ✅ Multiple container operations can be processed concurrently
- ✅ The application remains responsive under load

```python
# Example implementation pattern
async def create_container_async(container_config):
    return await asyncio.to_thread(docker_client.containers.run, **container_config)
```

---

### New API Endpoints

The service (container) management endpoints are located in `api/v1/services.py`:

- `GET /api/v1/services/all/` - List all monitoring services (with optional `active_only` filter)
- `POST /api/v1/services/start/` - Create and start a new monitoring service container
- `GET /api/v1/services/` - Get details for a specific monitoring service by container name or ID
- `DELETE /api/v1/services/stop/` - Stop and remove a monitoring service container

---

### Abuse Prevention & Resource Management

#### Rate Limiting (`slowapi`)

The rate limiting system is implemented at the FastAPI application layer using SlowAPI, which provides **in-memory rate limiting** without requiring database persistence.

Rate limits are enforced directly within the FastAPI middleware stack, allowing for **immediate request filtering** before any business logic execution kicks in. This early intervention prevents unnecessary **resource consumption** and protects the inner stack from propagating potential abuse.

Since the rate limiting operates in-memory rather than persisting limits to the database, it delivers **faster response times** and significantly reduces database load. This also bypasses any database connectivity issues that may arise under heavy load, thus providing an additional layer of system resilience.

Time windows and request quotas can be **configured "on-the-fly"** based on system capacity and usage patterns, ensuring fair resource allocation across clients while protecting both the FastAPI application and the underlying Docker daemon from overload conditions.

* ✅ Current implementation uses decorators like `@shared_limit_fetch` and `@shared_limit_execute`, capable of enforcing different rate limit policies based on operation impact.

```python
# Example SlowAPI configuration
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/hour"],
    storage_uri="memory://"
)

# Per-endpoint rate limits
@limiter.limit("10/minute")
async def create_service():
    pass
```

#### Concurrency Control (Asyncio Semaphore)

- ✅ Limits the number of concurrent Docker API calls (~5, can be configured manually or through env variables)
- Prevents overwhelming the Docker daemon
- ✅ Configurable semaphore count based on system resources

```python
# Example semaphore usage
docker_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent Docker operations

async def docker_operation():
    async with docker_semaphore:
        # Docker API call here
        pass
```

---

### Database Integration

#### MonitoringService Model

Currently the `MonitoringService` database model tracks all container operations with the following metadata:

- **ID**: Primary key string identifier for each monitoring service record
- **Container ID**: Docker-assigned container identifier (unique, nullable for flexibility)
- **Container Name**: Human-readable name of the monitoring service container (unique, required)
- **Stateful Set Name**: Kubernetes StatefulSet identifier (unique, nullable for future K8s integration)
- **MQTT Topic**: JSON field containing the MQTT topics being monitored by the service
- **Created At**: Timestamp recording when the monitoring service was created
- **Status**: Boolean flag indicating whether the service is active (True) or stopped (False)

Potential properties that should be considered include:

- **Image**: Docker image used for the container
- **Updated Timestamp**: Last modification time
- **Ports**: Port mappings and network configuration
- **Labels**: Custom labels and tags

#### Async Database Operations

✅ All database operations use SQLAlchemy's async drivers to maintain non-blocking behavior:

```python
# Example async database operation
async def create_service_record(session: AsyncSession, service_data: dict):
    service = AsyncMonitoringService(**service_data)
    session.add(service)
    await session.commit()
    return service
```

---

## (Potential) Environment Variables

```bash
# Docker configuration
DOCKER_HOST=unix:///var/run/docker.sock

# Rate limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=3600

# Concurrency
MAX_CONCURRENT_DOCKER_OPS=10
```

---

## Status of Current Implementation

There are three basic requirements to be met:

1. The application **MUST** handle communication with the Docker API in order to perform CRUD operations
2. The application **MUST** prevent abuse and overload of the Docker API
3. The application **MUST** maintain comprehensive logging across all user-facing operations

### Performance

✅ **Non-blocking I/O**: All Docker and database operations are asynchronous
✅ **Concurrent Processing**: Multiple requests can be handled simultaneously
✅ **Resource Efficiency**: Optimal use of system resources through semaphores

### Reliability

⚠️ **Error Handling**: Comprehensive error catching for Docker operations
✅ **Data Persistence**: All container operations are logged to the database
✅ **State Management**: Container states are tracked and maintained

### Security & Stability

✅ **Rate Limiting**: Prevents abuse and resource exhaustion
✅ **Concurrency Control**: Protects Docker daemon from overload
🔴 **Audit Trail**: Complete history of container operations

---

## Considerations

* ⚠️ The current implementation runs all components on a single host

* 🔴 `docker-py` binds directly with the docker system socket in the host

---

## What's next

### Scalability Improvements

- [ ] **Multi-host Support**: Extend to manage containers across multiple Docker hosts
- [ ] **Load Balancing**: Distribute container workloads across hosts
- [ ] **Clustering**: Implement Docker Swarm or Kubernetes integration

### Monitoring & Observability

- [ ] **Metrics Collection**: Integrate Prometheus for container metrics
- [ ] **Health Checks**: Automated container health monitoring
- [ ] **Alerting**: Notification system for container failures

### Security Enhancements

- [ ] **Authentication**: User-based access control
- [ ] **Authorization**: Role-based permissions for container operations
- [ ] **Network Isolation**: Enhanced container networking security
