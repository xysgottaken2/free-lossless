"""Tagged logging helpers.

Messages follow the format requested by the project:

    [DLSS5] Initializing...
    [DLSS5] Runtime: ...
    [DLSS5] Initialization failed
    [DLSS5] Reason: ...
    [RIFE] Frame Generation available

Nothing sensitive is ever logged (no user paths beyond the runtime folder
file name, no machine identifiers).
"""

from __future__ import annotations

import logging
import sys

_configured = False


def get_logger(name: str = "dlss5") -> logging.Logger:
    global _configured
    logger = logging.getLogger(f"freelossless.{name}")
    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger("freelossless")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _configured = True
    return logger


def log_dlss5(message: str) -> None:
    get_logger("dlss5").info("[DLSS5] %s", message)


def log_rife(message: str) -> None:
    get_logger("rife").info("[RIFE] %s", message)


def log_pipeline(message: str) -> None:
    get_logger("pipeline").info("[PIPELINE] %s", message)
