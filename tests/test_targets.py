"""Capture target tests: Window / Full Screen + monitor handling."""

import sys

from targets import (
    BACKEND_BITBLT,
    BACKEND_DXCAM,
    SOURCE_FULLSCREEN,
    SOURCE_WINDOW,
    CaptureTarget,
    MonitorInfo,
    capture_params_for,
    list_monitors,
    normalize_backend,
    normalize_source,
    resolve_capture_target,
)


def _monitors():
    return [
        MonitorInfo(index=0, rect=(0, 0, 1920, 1080), primary=True, name="Display 1"),
        MonitorInfo(index=1, rect=(1920, 0, 3840, 1080), primary=False, name="Display 2"),
    ]


def test_normalize_source_aliases():
    assert normalize_source("window") == SOURCE_WINDOW
    assert normalize_source("Window") == SOURCE_WINDOW
    assert normalize_source("fullscreen") == SOURCE_FULLSCREEN
    assert normalize_source("Full Screen") == SOURCE_FULLSCREEN
    assert normalize_source("full_screen") == SOURCE_FULLSCREEN
    assert normalize_source("desktop") == SOURCE_FULLSCREEN
    assert normalize_source(None) == SOURCE_WINDOW
    assert normalize_source("garbage") == SOURCE_WINDOW


def test_normalize_backend_aliases():
    assert normalize_backend("dxcam") == BACKEND_DXCAM
    assert normalize_backend("bitblt") == BACKEND_BITBLT
    assert normalize_backend("GDI") == BACKEND_BITBLT
    assert normalize_backend(None) == BACKEND_DXCAM


def test_list_monitors_always_has_primary():
    monitors = list_monitors()
    assert len(monitors) >= 1
    assert monitors[0].primary is True
    assert monitors[0].width > 0 and monitors[0].height > 0


def test_resolve_window_target_uses_window_rect():
    selection = {"source": "window", "hwnd": 42, "title": "Game"}
    target = resolve_capture_target(
        selection,
        monitors=_monitors(),
        window_rect_getter=lambda hwnd: (100, 50, 900, 650),
    )
    assert target.source == SOURCE_WINDOW
    assert target.rect == (100, 50, 900, 650)
    assert target.full_output is False
    assert target.width == 800 and target.height == 600
    assert target.label == "Game"


def test_resolve_window_without_hwnd_raises():
    try:
        resolve_capture_target({"source": "window"}, window_rect_getter=lambda h: (0, 0, 1, 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_resolve_fullscreen_target_uses_monitor():
    selection = {"source": "fullscreen", "monitor": 1}
    target = resolve_capture_target(selection, monitors=_monitors())
    assert target.source == SOURCE_FULLSCREEN
    assert target.rect == (1920, 0, 3840, 1080)
    assert target.full_output is True
    assert target.output_idx == 1
    assert "Full Screen" in target.label


def test_resolve_fullscreen_clamps_bad_monitor_index():
    for bad in (7, -3, "x", None):
        target = resolve_capture_target({"source": "fullscreen", "monitor": bad}, monitors=_monitors())
        assert target.output_idx == 0
        assert target.rect == (0, 0, 1920, 1080)


def test_capture_params_reuse_existing_backends():
    window_target = CaptureTarget(source=SOURCE_WINDOW, rect=(0, 0, 800, 600), output_idx=0)
    fs_target = CaptureTarget(source=SOURCE_FULLSCREEN, rect=(0, 0, 1920, 1080), output_idx=0, full_output=True)

    # dxcam window mode: region-based grab (as always)
    params = capture_params_for(window_target, BACKEND_DXCAM)
    assert params["region"] == (0, 0, 800, 600)

    # dxcam full screen: whole output of the selected monitor
    params = capture_params_for(fs_target, BACKEND_DXCAM)
    assert params["region"] is None
    assert params["output_idx"] == 0

    # bitblt uses screen-coordinate regions for both modes
    params = capture_params_for(fs_target, BACKEND_BITBLT)
    assert params["region"] == (0, 0, 1920, 1080)
    params = capture_params_for(window_target, BACKEND_BITBLT)
    assert params["region"] == (0, 0, 800, 600)


def test_monitor_label_marks_primary():
    monitors = _monitors()
    assert "Primary" in monitors[0].label
    assert "Primary" not in monitors[1].label
