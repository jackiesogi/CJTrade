"""Sinopac (shioaji) broker adapter."""
import os

from cjtrade.pkgs import paths

# shioaji opens its log file when it is imported, at $SJ_LOG_PATH or else
# ./shioaji.log, so every directory cjtrade was started in collected one.
# Point it at the log directory unless the caller chose a place. This has to
# run before anything imports shioaji, which is why it is here.
os.environ.setdefault("SJ_LOG_PATH", str(paths.log_path("shioaji.log")))
