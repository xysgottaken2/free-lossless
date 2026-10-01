"""Load platform-specific modules without requiring a GPU or a Windows desktop."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

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
