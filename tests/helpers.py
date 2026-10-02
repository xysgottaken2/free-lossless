"""Load platform-specific modules without requiring a GPU or a Windows desktop."""
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

# Tests must never write into the log of a real session running on this machine.
os.environ.setdefault("FREE_LOSSLESS_LOG", "0")

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, dependencies, runtime=False):
    """Import a module for testing; ``runtime`` also resolves its lazy imports."""
    spec = importlib.util.spec_from_file_location(f"test_subject_{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
        # main.py loads OpenCV/pygame/pywin32 through load_runtime(); tests that call
        # into the overlay resolve them against the stubs.
        if runtime and hasattr(module, "load_runtime"):
            module.load_runtime()
    return module


def stubs(*names):
    return {name: MagicMock(name=name) for name in names}


def silence_diagnostics(test):
    """Send the shared diagnostics log nowhere for one test, and restore it afterwards.

    ``diagnostics`` is a real module shared by every test in the run, so a leftover
    lambda here silently swallows the messages another test is asserting on — which is
    how a green suite turns red for no visible reason.
    """
    import diagnostics as diagnostics_module
    original = (diagnostics_module.write, diagnostics_module.write_now, diagnostics_module.ENABLED)

    def restore():
        (diagnostics_module.write, diagnostics_module.write_now,
         diagnostics_module.ENABLED) = original

    test.addCleanup(restore)
    diagnostics_module.ENABLED = False
    diagnostics_module.write = lambda message: None
    diagnostics_module.write_now = lambda label, message: None
    return restore
