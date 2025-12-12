"""
Shared pytest fixtures and configuration for MQTT Proxy tests
"""

import pytest
import asyncio
from dotenv import load_dotenv


@pytest.fixture(scope='session', autouse=True)
def load_env():
    load_dotenv()


@pytest.fixture(scope="session")
def event_loop_policy():
    """Set event loop policy for all tests"""
    return asyncio.DefaultEventLoopPolicy()
