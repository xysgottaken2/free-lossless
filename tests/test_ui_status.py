"""UI status helper tests (requirement 9 & 18 - status block content)."""

from ui_status import build_dlss5_status_lines, describe_runtime


def test_status_block_lines():
    lines = build_dlss5_status_lines("Found (310.8.0.0)", "NVIDIA GeForce RTX 2060",
                                     "ngx-core+dlssnr", "Ready")
    assert lines[0] == "Runtime: Found (310.8.0.0)"
    assert lines[1] == "GPU: NVIDIA GeForce RTX 2060"
    assert lines[2] == "Backend: ngx-core+dlssnr"
    assert lines[3] == "Status: Ready"


def test_status_block_defaults():
    lines = build_dlss5_status_lines("", "", "", "")
    assert lines[0] == "Runtime: Not Found"
    assert lines[1] == "GPU: unknown"
    assert lines[2] == "Backend: none"
    assert lines[3] == "Status: Disabled"


def test_describe_runtime():
    assert describe_runtime(False) == "Not Found"
    assert describe_runtime(True, "310.8.0.0") == "Found (310.8.0.0)"
    assert describe_runtime(True, "unknown") == "Found"
