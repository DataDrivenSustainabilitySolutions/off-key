"""
Entry point for MQTT bridge service package execution.

This module serves as the main entry point when running the MQTT service package
with `python -m off_key.services.mqtt`. It prevents RuntimeWarning issues that
occur when a module is both imported as a package component and executed as a script.
"""

import asyncio
from .bridge import main

if __name__ == "__main__":
    asyncio.run(main())
