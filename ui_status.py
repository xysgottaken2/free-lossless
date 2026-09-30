"""Pure helpers for the DLSS 5 status panel (kept Tk-free for unit tests)."""

from __future__ import annotations

from typing import List


def build_dlss5_status_lines(runtime_text: str, gpu: str, backend: str, status: str) -> List[str]:
    """Exactly the status block shown in the UI:

    Runtime: Not Found
    GPU: RTX 2060
    Backend: ...
    Status: Disabled
    """
    return [
        f"Runtime: {runtime_text or 'Not Found'}",
        f"GPU: {gpu or 'unknown'}",
        f"Backend: {backend or 'none'}",
        f"Status: {status or 'Disabled'}",
    ]


def describe_runtime(present: bool, version: str = "unknown") -> str:
    if not present:
        return "Not Found"
    if version and version != "unknown":
        return f"Found ({version})"
    return "Found"
