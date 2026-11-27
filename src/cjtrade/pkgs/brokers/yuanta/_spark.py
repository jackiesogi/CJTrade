"""Load Yuanta's Spark API: a .NET 8 assembly, ``YuantaSparkAPI.dll``, through pythonnet.

Yuanta does not publish the API on PyPI. It ships as a folder of .dll, .so and
.dylib files with its sample code; this module needs that folder's path and a
.NET 8 runtime. Everything the adapter uses from the assembly comes back in one
namespace, so tests can hand the adapter a fake instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

_loaded: Optional[SimpleNamespace] = None


class SparkUnavailable(ImportError):
    """The Spark API could not be loaded: pythonnet, .NET 8 or the DLL is missing."""


def load(dll_dir: str) -> SimpleNamespace:
    """Load the assembly from `dll_dir` once and return its classes and enums.

    Raises
    ------
    SparkUnavailable
        pythonnet is not installed, the .NET runtime cannot start, or
        ``YuantaSparkAPI.dll`` is not in `dll_dir`.
    """
    global _loaded
    if _loaded is not None:
        return _loaded
    folder = Path(dll_dir or "").expanduser()
    if not (folder / "YuantaSparkAPI.dll").is_file():
        raise SparkUnavailable(
            f"YuantaSparkAPI.dll not found in {folder!s}; set YUANTA_DLL_DIR to the "
            "folder of Yuanta's Spark API files")
    try:
        from pythonnet import load as load_runtime
        load_runtime("coreclr")
        import clr  # noqa: F401 - provided by pythonnet
    except Exception as e:  # noqa: BLE001 - ImportError, or a runtime that fails to start
        raise SparkUnavailable(
            f"pythonnet with a .NET 8 runtime is needed for Yuanta ({e}); "
            "pip install 'cjtrade[yuanta]' and install .NET 8") from e
    sys.path.append(str(folder))
    if sys.platform == "win32":
        os.add_dll_directory(str(folder))
    try:
        clr.AddReference("System.Collections")
        clr.AddReference("YuantaSparkAPI")
        from System.Collections.Generic import List
        import YuantaOneAPI as api
    except Exception as e:  # noqa: BLE001
        raise SparkUnavailable(f"loading YuantaSparkAPI.dll from {folder!s} failed: {e}") from e
    _loaded = SimpleNamespace(
        Trader=api.YuantaSparkAPITrader,
        StockOrder=api.StockOrder,
        Quote=api.Quote,
        List=List,
        enumEnvironmentMode=api.enumEnvironmentMode,
        enumLangType=api.enumLangType,
        enumLogType=api.enumLogType,
        enumMarketType=api.enumMarketType,
    )
    return _loaded
