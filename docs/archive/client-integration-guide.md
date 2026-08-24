> [!WARNING]
> This page is **legacy / archived** and may be outdated.
> It is preserved for historical context only and is **not** the source of truth for current operations.
>
> Use current documentation instead:
- [Developer-Setup](../development/setup.md)
- [Architecture-Overview](../development/architecture.md)
>
> You can also start from [Archive / Legacy Index](index.md).

---
# Client Integration Guide

## Overview

The Off-Key backend implements a **plug-and-play architecture** using Dependency Injection (DI) that enables seamless integration of new external API clients without modifying existing business logic. The system uses Python's Protocol-based structural typing and FastAPI's dependency injection framework to achieve complete decoupling between services and API providers. This architecture allows you to switch between different charger API providers (Pionix, or any future APIs) by simply implementing the required interface and updating a single environment variable.

## Integration Steps

### Step 1: Implement the Client Interface

Create your new client by implementing the `ChargerAPIClient` protocol:

```python
# backend/src/off_key/core/client/your_provider_client.py

from typing import Dict, Any, List, Optional
import httpx
from .base_client import ChargerAPIClient
from .your_provider_config import YourProviderConfig
from ...core.logs import logger

class YourProviderClient:
    """Client for YourProvider API - implements ChargerAPIClient protocol"""

    def __init__(self, config: YourProviderConfig):
        self.config = config
        self.client = httpx.AsyncClient()

    async def get_chargers(self) -> List[Dict[str, Any]]:
        """Get all active chargers from YourProvider API"""
        # Implement your API call logic here
        response = await self.client.get(
            f"{self.config.base_url}/devices",
            headers={"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"}
        )
        return response.json()

    async def get_device_info(self, charger_id: str) -> Dict[str, Any]:
        """Get device information for a specific charger"""
        response = await self.client.get(
            f"{self.config.base_url}/devices/{charger_id}/info",
            headers={"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"}
        )
        return response.json()

    async def get_telemetry_data(
        self, charger_id: str, hierarchy: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get telemetry data for a charger"""
        params = {"metric": hierarchy}
        if limit:
            params["limit"] = limit

        response = await self.client.get(
            f"{self.config.base_url}/devices/{charger_id}/telemetry",
            headers={"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"},
            params=params
        )
        return response.json()
```

### Step 2: Create Configuration Model

Define a pure data configuration class:

```python
# backend/src/off_key/core/client/your_provider_config.py

from pydantic import BaseModel, SecretStr

class YourProviderConfig(BaseModel):
    """Configuration for YourProvider API client"""

    base_url: str = "https://api.yourprovider.com/v1"
    api_key: SecretStr
    user_agent: str

    # Provider-specific configuration
    timeout: int = 30
    max_retries: int = 3

    class Config:
        extra = "forbid"
```

### Step 3: Update Dependency Provider

Add your provider to the central dependency resolver:

```python
# backend/src/off_key/core/dependencies.py

@lru_cache()
def get_charger_api_client() -> ChargerAPIClient:
    """Dependency provider for charger API client"""
    provider = getattr(settings, 'CHARGER_API_PROVIDER', 'pionix')

    if provider == "pionix":
        return PionixClient(config=settings.pionix_config)
    elif provider == "yourprovider":  # Add your provider here
        from .client.your_provider_client import YourProviderClient
        return YourProviderClient(config=settings.your_provider_config)
    else:
        raise ValueError(
            f"Unknown charger API provider: {provider}. "
            f"Valid options are: 'pionix', 'yourprovider'"
        )
```

### Step 4: Update Settings

Add configuration support to the main settings class:

```python
# backend/src/off_key/core/config.py

class Settings(BaseSettings):
    # Existing settings...

    # Your provider configuration
    YOUR_PROVIDER_API_KEY: str = ""
    YOUR_PROVIDER_USER_AGENT: str = "off-key-backend/1.0"
    YOUR_PROVIDER_BASE_URL: str = "https://api.yourprovider.com/v1"

    @property
    def your_provider_config(self) -> "YourProviderConfig":
        """Create YourProviderConfig instance from settings"""
        from ..core.client.your_provider_config import YourProviderConfig

        return YourProviderConfig(
            api_key=self.YOUR_PROVIDER_API_KEY,
            user_agent=self.YOUR_PROVIDER_USER_AGENT,
            base_url=self.YOUR_PROVIDER_BASE_URL
        )
```

### Step 5: Environment Configuration

Set the environment variable to use your new provider:

```bash
# .env file
CHARGER_API_PROVIDER=yourprovider
YOUR_PROVIDER_API_KEY=<provider-api-key>
YOUR_PROVIDER_USER_AGENT=off-key-backend/1.0
```

## Testing Your Integration

### Unit Testing

Test your client implementation with mocks:

```python
# tests/test_your_provider_client.py

import pytest
from unittest.mock import Mock, AsyncMock
from off_key.core.client.your_provider_client import YourProviderClient
from off_key.core.client.your_provider_config import YourProviderConfig

@pytest.fixture
def client_config():
    return YourProviderConfig(
        api_key="test_key",
        user_agent="test_agent"
    )

@pytest.fixture
def client(client_config):
    return YourProviderClient(client_config)

@pytest.mark.asyncio
async def test_get_chargers(client):
    # Mock the HTTP client
    client.client.get = AsyncMock()
    client.client.get.return_value.json.return_value = [
        {"id": "charger_1", "name": "Test Charger"}
    ]

    result = await client.get_chargers()

    assert len(result) == 1
    assert result[0]["id"] == "charger_1"
```

### Integration Testing

Test with dependency injection:

```python
# tests/test_integration.py

@pytest.mark.asyncio
async def test_service_with_your_provider():
    # Create your client
    config = YourProviderConfig(api_key="test_key", user_agent="test")
    client = YourProviderClient(config)

    # Inject into service (no business logic changes needed!)
    async with get_test_db_session() as session:
        service = ChargersSyncService(session, client)
        await service.sync_chargers()
```

## Architecture Benefits

### Zero Business Logic Changes
- Services remain completely unchanged
- All business logic continues to work identically
- No coupling between services and specific providers

### Type Safety
- Protocol ensures compile-time interface checking
- Pydantic models provide runtime validation
- IDE support for auto-completion and error detection

### Configuration-Driven
- Switch providers via environment variables
- No code deployment required for provider changes
- Support for provider-specific configuration

### Testability
- Easy dependency injection for unit tests
- Mock any provider implementation
- Test services independently of external APIs

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure your client modules are properly structured and importable
2. **Protocol Compliance**: Verify all three methods (`get_chargers`, `get_device_info`, `get_telemetry_data`) are implemented
3. **Configuration Validation**: Check Pydantic model validation for required fields
4. **Environment Variables**: Ensure all required environment variables are set

### Debug Mode

Enable debug logging to trace dependency resolution:

```python
# Set in environment
LOG_LEVEL=DEBUG

# Check startup logs for:
# "Initialized API client: YourProviderClient"
```

## Migration Strategy

When switching from one provider to another:

1. Implement new client following this guide
2. Test thoroughly in development environment
3. Update environment variables
4. Deploy - zero downtime migration
5. Monitor logs for successful provider initialization

## Conclusion

This architecture demonstrates enterprise-grade Dependency Injection patterns, making the Off-Key backend truly provider-agnostic. The Protocol-based design ensures type safety while maintaining flexibility, and the centralized dependency resolution provides a clean separation of concerns. Adding new providers requires no changes to existing business logic, making the system highly maintainable and extensible.
