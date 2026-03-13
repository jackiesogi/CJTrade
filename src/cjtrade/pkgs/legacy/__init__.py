# main.py (skeleton, put under src/cjtrade or project root)
import asyncio
import logging
import signal
from datetime import datetime
from datetime import timedelta

def cli():
    """同步 entrypoint，用於 pyproject.toml"""
    from .app import main as _main
    asyncio.run(_main())
