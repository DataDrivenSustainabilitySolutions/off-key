"""
Entry point for database sync service package execution.

This module serves as the main entry point when running the service with
`python -m aberration_db_sync`.
"""

import asyncio

from .main import main

if __name__ == "__main__":
    asyncio.run(main())
