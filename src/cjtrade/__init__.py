# main.py (skeleton, put under src/cjtrade or project root)
import asyncio
import signal
import logging
from datetime import datetime, timedelta
from .app import main as _main

def cli():
    """同步 entrypoint，用於 pyproject.toml"""
    asyncio.run(_main())