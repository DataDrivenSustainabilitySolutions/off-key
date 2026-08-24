!!! warning "Archived page"
    This page is retained for historical reference and may not match the present implementation.

    Maintained guidance:

    - [Environment variables](../reference/environment-variables.md)
    - [Testing and debugging](../development/testing-debugging.md)
    - [Archive index](index.md)

---
# Centralized Logging Documentation

## Overview
The application implements enterprise-grade centralized logging using Python's standard `logging` library with FastAPI integration. All logging is environment-configurable and production-ready.

## Architecture

### Core Components
- **`core/logs.py`** - Central logging configuration and utilities
- **`core/config.py`** - Environment-based logging settings
- **`api/middleware.py`** - FastAPI middleware for request/security logging
- **`main.py`** - Application-wide logging initialization

## Configuration

### Environment Variables
All variables are optional with sensible defaults:

```bash
# Logging Configuration
LOG_LEVEL=INFO                           # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT=simple                        # simple or json
LOG_CORRELATION_HEADER=X-Correlation-ID  # Header for correlation IDs
ENABLE_REQUEST_LOGGING=true              # Log all API requests/responses
ENABLE_PERFORMANCE_LOGGING=true          # Log timing information
```

### Environment-Specific Configurations

**Development:**
```bash
LOG_LEVEL=DEBUG
LOG_FORMAT=simple
ENABLE_REQUEST_LOGGING=true
```

**Production:**
```bash
LOG_LEVEL=WARNING
LOG_FORMAT=json
ENABLE_PERFORMANCE_LOGGING=true
```

## Usage

### Basic Logging
```python
from off_key.core.logs import logger

logger.info("Operation completed successfully")
logger.warning("Potential issue detected")
logger.error("Operation failed", exc_info=True)
```

### Performance Logging
```python
from off_key.core.logs import log_performance
import time

start_time = time.time()
# ... your operation ...
log_performance("database_sync", start_time)
```

### Security Event Logging
```python
from off_key.core.logs import log_security_event

log_security_event(
    event_type="failed_login",
    user_id="user@example.com",
    details={"ip": "192.168.1.1", "attempts": 3}
)
```

### Correlation ID Management
```python
from off_key.core.logs import set_correlation_id, get_correlation_id

# Set correlation ID (usually done by middleware)
set_correlation_id("req-12345")

# Get current correlation ID
current_id = get_correlation_id()
```

## Log Formats

### Simple Format (Development)
```
2024-01-15 10:30:45,123 - INFO - off_key.services.telemetry - [req-abc123] - Sync completed successfully
```

### JSON Format (Production)
```json
{
  "timestamp": "2024-01-15 10:30:45,123",
  "level": "INFO",
  "logger": "off_key.services.telemetry",
  "message": "Sync completed successfully",
  "correlation_id": "req-abc123",
  "module": "telemetry",
  "function": "sync_data",
  "line": 45
}
```

## Request Logging

### Automatic Request Tracking
The FastAPI middleware automatically logs:
- **Incoming requests**: Method, path, query parameters, user agent
- **Response status**: Status code, content type
- **Performance timing**: Request duration
- **Error context**: Full request details for failed requests

### Correlation ID Headers
- **Incoming**: Reads `X-Correlation-ID` header if provided
- **Outgoing**: Adds `X-Correlation-ID` header to all responses
- **Generation**: Creates UUID if no correlation ID provided

## Security Logging

### Automatic Security Events
- **Authentication failures** (401 responses)
- **Authorization failures** (403 responses)
- **Suspicious request patterns** (directory traversal, injection attempts)

### Manual Security Logging
```python
from off_key.core.logs import log_security_event

# Log custom security events
log_security_event("password_reset", user_id="user123", details={"ip": client_ip})
```

## Best Practices

### Do's
- Use appropriate log levels (DEBUG for development, WARNING+ for production)
- Include context in log messages (user ID, operation type, etc.)
- Use performance logging for operations that might be slow
- Log security events for audit trails

### Don'ts
- Don't log sensitive information (passwords, tokens, API keys)
- Don't use print statements (use logger instead)
- Don't log at DEBUG level in production
- Don't include full request/response bodies in logs

### Log Levels Guidelines
- **DEBUG**: Detailed information for troubleshooting
- **INFO**: General operational information
- **WARNING**: Something unexpected happened but not an error
- **ERROR**: Error occurred, but application can continue
- **CRITICAL**: Serious error, application might not continue

## Monitoring Integration

### JSON Logs for Aggregation
When `LOG_FORMAT=json`, logs are structured for:
- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Splunk**
- **Datadog**
- **Grafana Loki**

### Key Fields for Monitoring
- `correlation_id` - Request tracing
- `level` - Alert severity
- `logger` - Component identification
- `timestamp` - Time series analysis

## Troubleshooting

### Common Issues
1. **Logs not appearing**: Check `LOG_LEVEL` setting
2. **No correlation IDs**: Ensure middleware is properly configured
3. **Duplicate logs**: Check for multiple logger configurations
4. **Performance impact**: Reduce log level or disable request logging

### Debug Mode
```bash
LOG_LEVEL=DEBUG
LOG_FORMAT=simple
ENABLE_REQUEST_LOGGING=true
```

### Minimal Production Mode
```bash
LOG_LEVEL=ERROR
LOG_FORMAT=json
ENABLE_REQUEST_LOGGING=false
ENABLE_PERFORMANCE_LOGGING=false
```

## Migration Notes

### Backward Compatibility
- All existing `logger.info()`, `logger.error()` calls work unchanged
- No code changes required for basic functionality
- Enhanced features are opt-in via configuration

### Upgraded Components
- `services/resources/proxy.py` - MQTT routing now uses proper logging
- `scripts/create_admin.py` - Admin creation events logged
- `services/mqtt.py` - MQTT client errors properly handled

This logging system provides enterprise-grade observability while maintaining simplicity and backward compatibility.
